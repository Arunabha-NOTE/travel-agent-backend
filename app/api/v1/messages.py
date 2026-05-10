"""Messages API — SSE streaming endpoint for LangChain/LangGraph agents."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from time import perf_counter
import re
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.agents.guardrails import evaluate_user_prompt
from app.core import ResourceNotFoundError, get_logger
from app.models.chat_message import ChatMessage, MessageSenderRole
from app.models.chat_room import ChatRoom
from app.models.chat_itinerary import ChatItinerary
from app.models.planning_session import PlanningSession, PLANNING_STAGES
from app.models.user import User

logger = get_logger(__name__)

router = APIRouter(prefix="/chats", tags=["messages"])

_DEFAULT_CHAT_TITLES = {"new chat", "", "new conversation"}
_LEAKED_TITLE_MARKERS = [
    "the user",
    "asking for",
    "summarize",
    "title for",
    "generate a",
]

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]")
_KNOWN_PROBLEMATIC_CHARS = {"\ua9c5", "\U0001242b"}


def _normalize_planning_stage(stage: str | None) -> str:
    value = (stage or "initial").strip().lower()
    if value == "flights":
        return "transport"
    return value or "initial"


class SendMessageRequest(BaseModel):
    """Send a chat message request."""

    content: str = Field(min_length=1, max_length=8192)
    agent: str = Field(default="langchain", pattern=r"^(langchain|langgraph)$")

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Message cannot be empty")
        if _CONTROL_CHAR_RE.search(normalized):
            raise ValueError("Message contains unsupported control characters")
        if any(char in _KNOWN_PROBLEMATIC_CHARS for char in normalized):
            raise ValueError("Message contains unsupported characters")
        return normalized


class MessageResponse(BaseModel):
    """Response schema for a single chat message."""

    id: int
    chat_room_id: uuid.UUID
    sender_role: str
    content: str
    created_at: datetime
    message_metadata: dict | None = None


async def _get_owned_chat_or_404(
    *,
    db: AsyncSession,
    chat_id: uuid.UUID,
    user_id: int,
) -> ChatRoom:
    result = await db.execute(
        select(ChatRoom).where(
            and_(
                ChatRoom.id == chat_id,
                ChatRoom.user_id == user_id,
                ChatRoom.archived_at.is_(None),
            )
        )
    )
    chat = result.scalars().first()
    if chat is None:
        raise ResourceNotFoundError(resource="ChatRoom", resource_id=chat_id)
    return chat


@router.get("/{chat_id}/messages", response_model=list[MessageResponse])
async def list_messages(
    chat_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all messages in a chat room."""
    await _get_owned_chat_or_404(db=db, chat_id=chat_id, user_id=current_user.id)

    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.chat_room_id == chat_id)
        .order_by(ChatMessage.created_at.asc())
    )
    messages = result.scalars().all()

    return [
        MessageResponse(
            id=m.id,
            chat_room_id=m.chat_room_id,
            sender_role=m.sender_role.value,
            content=m.content,
            created_at=m.created_at,
            message_metadata=m.message_metadata,
        )
        for m in messages
    ]


@router.post("/{chat_id}/messages")
async def send_message(
    chat_id: uuid.UUID,
    payload: SendMessageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Send a message and stream the agent response via SSE.

    Response is `text/event-stream`. Each line is:
      `data: <token>\\n\\n`
    Ends with:
      `data: [DONE]\\n\\n`
    """
    request_started_at = perf_counter()
    logger.info(
        "Send message request started",
        chat_id=chat_id,
        user_id=current_user.id,
        agent=payload.agent,
        message_chars=len(payload.content),
    )

    await _get_owned_chat_or_404(db=db, chat_id=chat_id, user_id=current_user.id)

    blocked, blocked_reason = evaluate_user_prompt(payload.content)
    if blocked:
        logger.warning(
            "User message blocked by guardrails",
            chat_id=chat_id,
            user_id=current_user.id,
            reason=blocked_reason,
        )

        refusal = (
            "I can't help with overriding instructions or exposing internal prompts, "
            "queries, credentials, or other sensitive backend information. "
            "I can still help with your travel planning request."
        )

        user_msg = ChatMessage(
            chat_room_id=chat_id,
            sender_role=MessageSenderRole.user,
            sender_user_id=current_user.id,
            content=payload.content,
            message_metadata={"guardrail_blocked": True, "reason": blocked_reason},
        )
        db.add(user_msg)

        chat_result = await db.execute(select(ChatRoom).where(ChatRoom.id == chat_id))
        chat = chat_result.scalars().first()
        if chat:
            chat.updated_at = datetime.now(timezone.utc)

        assistant_msg = ChatMessage(
            chat_room_id=chat_id,
            sender_role=MessageSenderRole.assistant,
            content=refusal,
            message_metadata={
                "agent": "guardrail",
                "guardrail_blocked": True,
                "reason": blocked_reason,
            },
        )
        db.add(assistant_msg)
        await db.commit()

        async def blocked_stream():
            safe_token = refusal.replace("\n", "\\n")
            yield f"data: {safe_token}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            blocked_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    # Save user message
    user_msg = ChatMessage(
        chat_room_id=chat_id,
        sender_role=MessageSenderRole.user,
        sender_user_id=current_user.id,
        content=payload.content,
    )
    db.add(user_msg)

    # Update chat room updated_at
    chat_result = await db.execute(select(ChatRoom).where(ChatRoom.id == chat_id))
    chat = chat_result.scalars().first()
    if chat:
        chat.updated_at = datetime.now(timezone.utc)

    await db.commit()

    # Load chat history (last 20 messages for context)
    history_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.chat_room_id == chat_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(21)
    )
    history_msgs = list(reversed(history_result.scalars().all()))

    # Auto-title: if this was the FIRST message or we have a leaked/default title,
    # fire a background task to generate and save a descriptive title.
    # history_msgs includes the user's message we just added.
    is_early_stage = len(history_msgs) <= 4  # Allow retry on first 2 exchanges
    title_is_default = chat.title.lower() in _DEFAULT_CHAT_TITLES
    title_is_leaked = any(p in chat.title.lower() for p in _LEAKED_TITLE_MARKERS)

    if (is_early_stage and chat) and (title_is_default or title_is_leaked):
        logger.info(
            "Auto-title scheduled",
            chat_id=chat_id,
            user_id=current_user.id,
            is_early_stage=is_early_stage,
            title_is_default=title_is_default,
            title_is_leaked=title_is_leaked,
        )

        async def _auto_title() -> None:
            try:
                from app.agents.titler import generate_chat_title
                from app.db.session import async_session_maker

                # Prefer titling directly from the very first user query.
                if (
                    len(history_msgs) == 1
                    and history_msgs[0].sender_role == MessageSenderRole.user
                ):
                    title_seed: str | list[dict[str, str]] = payload.content
                else:
                    context = []
                    for msg in history_msgs:
                        context.append(
                            {
                                "role": msg.sender_role.value
                                if hasattr(msg.sender_role, "value")
                                else str(msg.sender_role),
                                "content": msg.content,
                            }
                        )
                    title_seed = context

                title = await generate_chat_title(title_seed)
                if title:
                    async with async_session_maker() as title_db:
                        result = await title_db.execute(
                            select(ChatRoom).where(ChatRoom.id == chat_id)
                        )
                        room = result.scalars().first()
                        if room:
                            current_title = (room.title or "").strip().lower()
                            title_still_replaceable = (
                                current_title in _DEFAULT_CHAT_TITLES
                                or any(
                                    marker in current_title
                                    for marker in _LEAKED_TITLE_MARKERS
                                )
                            )
                            if title_still_replaceable:
                                room.title = title
                                room.updated_at = datetime.now(timezone.utc)
                                await title_db.commit()
                                logger.info(
                                    "Auto-title committed",
                                    chat_id=chat_id,
                                    user_id=current_user.id,
                                    title=title,
                                )
                            else:
                                logger.info(
                                    "Auto-title skipped because chat already renamed",
                                    chat_id=chat_id,
                                    user_id=current_user.id,
                                    current_title=room.title,
                                )
            except Exception as e:
                logger.warning(
                    "Auto-title background task failed",
                    chat_id=chat_id,
                    user_id=current_user.id,
                    error=str(e),
                )

        asyncio.create_task(_auto_title())

    # Auto-summarizer logic check
    from app.agents.summarizer import check_and_summarize

    asyncio.create_task(check_and_summarize(chat_id))

    # Exclude the current user message from the history passed to the agent
    history = [
        {"role": m.sender_role.value, "content": m.content}
        for m in history_msgs[:-1]
        if m.sender_role in (MessageSenderRole.user, MessageSenderRole.assistant)
    ]

    # Inject itinerary, planning stage, and conversation summary into system context
    system_parts = []
    if chat and chat.context_summary:
        system_parts.append(
            f"## Conversation Summary (earlier messages)\n{chat.context_summary}"
        )

    itinerary_res = await db.execute(
        select(ChatItinerary).where(ChatItinerary.chat_room_id == chat_id)
    )
    itinerary = itinerary_res.scalars().first()
    itinerary_days = 0
    if itinerary and itinerary.itinerary_data:
        import json

        if isinstance(itinerary.itinerary_data, dict):
            raw_days = itinerary.itinerary_data.get("days")
            if isinstance(raw_days, list):
                itinerary_days = len([day for day in raw_days if isinstance(day, dict)])

        itinerary_str = json.dumps(itinerary.itinerary_data, indent=2)
        system_parts.append(
            f"## Current Itinerary (UPDATE and re-emit, preserving all confirmed fields)\n"
            f"```json\n{itinerary_str}\n```"
        )

    # Planning session — stage + preferences
    planning_res = await db.execute(
        select(PlanningSession).where(PlanningSession.chat_room_id == chat_id)
    )
    planning = planning_res.scalars().first()
    current_stage = _normalize_planning_stage(planning.stage if planning else "initial")

    stage_index = (
        PLANNING_STAGES.index(current_stage) if current_stage in PLANNING_STAGES else 0
    )
    stage_progress = " → ".join(
        f"**[{s.upper()}]**" if s == current_stage else s for s in PLANNING_STAGES
    )

    pref_lines = []
    if planning and planning.preferences:
        p = planning.preferences
        if p.get("origin"):
            pref_lines.append(f"- Origin: {p['origin']}")
        if p.get("destination"):
            pref_lines.append(f"- Destination: {p['destination']}")
        if p.get("people", {}).get("adults"):
            adults = p["people"]["adults"]
            children = p["people"].get("children", 0)
            pref_lines.append(f"- Group: {adults} adults, {children} children")
        if p.get("budget", {}).get("amount"):
            b = p["budget"]
            pref_lines.append(
                f"- Budget: {b.get('currency', '')} {b['amount']} ({b.get('type', 'total')})"
            )
        if p.get("dates", {}).get("start"):
            d = p["dates"]
            pref_lines.append(f"- Dates: {d['start']} to {d.get('end', '?')}")
        if p.get("flights", {}).get("selected"):
            pref_lines.append(f"- Transport confirmed: {p['flights']['selected']}")
        if p.get("hotels", {}).get("selected"):
            pref_lines.append(f"- Hotel confirmed: {p['hotels']['selected']}")

    planning_block = (
        f"## Planning Progress: {stage_progress}\n"
        f"**Current stage: {current_stage.upper()}**\n"
    )
    if pref_lines:
        planning_block += "\n### Confirmed so far:\n" + "\n".join(pref_lines)
    system_parts.append(planning_block)

    if system_parts:
        history.insert(
            0, {"role": "system", "content": "\n\n---\n\n".join(system_parts)}
        )

    logger.info(
        "Prepared agent context",
        chat_id=chat_id,
        user_id=current_user.id,
        itinerary_loaded=itinerary is not None,
        itinerary_days=itinerary_days,
        planning_stage=current_stage,
        planning_stage_index=stage_index,
        preference_lines=len(pref_lines),
        history_messages=len(history),
    )

    logger.info(
        "Starting agent stream",
        chat_id=chat_id,
        agent=payload.agent,
        user_id=current_user.id,
        elapsed_ms=round((perf_counter() - request_started_at) * 1000, 2),
    )

    async def event_stream():
        stream_started_at = perf_counter()
        try:
            if payload.agent == "langchain":
                from app.agents.langchain_agent import run_langchain_agent

                gen = run_langchain_agent(
                    chat_id=chat_id,
                    user_message=payload.content,
                    history=history,
                    db=db,
                    user_id=current_user.id,
                )
            else:
                from app.agents.langgraph_agent import run_langgraph_agent

                gen = run_langgraph_agent(
                    chat_id=chat_id,
                    user_message=payload.content,
                    history=history,
                    db=db,
                    user_id=current_user.id,
                )

            import asyncio

            while True:
                try:
                    # Keep-alive every 15 seconds to prevent frontend timeout
                    token = await asyncio.wait_for(anext(gen), timeout=15.0)
                    # [STEP:...] markers are passed as-is; other tokens escape newlines
                    if token.startswith("[STEP:"):
                        yield f"data: {token}\n\n"
                    else:
                        safe_token = token.replace("\n", "\\n")
                        yield f"data: {safe_token}\n\n"
                except asyncio.TimeoutError:
                    yield "data: [KEEPALIVE]\n\n"
                except StopAsyncIteration:
                    break

        except Exception as e:
            logger.exception("Stream error", error=str(e))
            yield f"data: [ERROR] {e}\n\n"
        finally:
            logger.info(
                "Agent stream closed",
                chat_id=chat_id,
                agent=payload.agent,
                user_id=current_user.id,
                elapsed_ms=round((perf_counter() - stream_started_at) * 1000, 2),
            )
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
