"""Messages API — SSE streaming endpoint for LangChain/LangGraph agents."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core import ResourceNotFoundError, get_logger
from app.models.chat_message import ChatMessage, MessageSenderRole
from app.models.chat_room import ChatRoom
from app.models.user import User

logger = get_logger(__name__)

router = APIRouter(prefix="/chats", tags=["messages"])


class SendMessageRequest(BaseModel):
    """Send a chat message request."""

    content: str = Field(min_length=1, max_length=8192)
    agent: str = Field(default="langchain", pattern=r"^(langchain|langgraph)$")


class MessageResponse(BaseModel):
    """Response schema for a single chat message."""

    id: int
    chat_room_id: int
    sender_role: str
    content: str
    created_at: datetime
    message_metadata: dict | None = None


async def _get_owned_chat_or_404(
    *,
    db: AsyncSession,
    chat_id: int,
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
    chat_id: int,
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
    chat_id: int,
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
    await _get_owned_chat_or_404(db=db, chat_id=chat_id, user_id=current_user.id)

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

    # Load chat history (last 20 messages)
    history_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.chat_room_id == chat_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(21)
    )
    history_msgs = list(reversed(history_result.scalars().all()))
    # Exclude the message we just saved (last one is user's current msg)
    history = [
        {"role": m.sender_role.value, "content": m.content}
        for m in history_msgs[:-1]
        if m.sender_role in (MessageSenderRole.user, MessageSenderRole.assistant)
    ]

    logger.info(
        "Starting agent stream",
        chat_id=chat_id,
        agent=payload.agent,
        user_id=current_user.id,
    )

    async def event_stream():
        try:
            if payload.agent == "langchain":
                from app.agents.langchain_agent import run_langchain_agent

                gen = run_langchain_agent(
                    chat_id=chat_id,
                    user_message=payload.content,
                    history=history,
                    db=db,
                )
            else:
                from app.agents.langgraph_agent import run_langgraph_agent

                gen = run_langgraph_agent(
                    chat_id=chat_id,
                    user_message=payload.content,
                    history=history,
                    db=db,
                )

            async for token in gen:
                # Escape newlines inside token for SSE
                safe_token = token.replace("\n", "\\n")
                yield f"data: {safe_token}\n\n"

        except Exception as e:
            logger.exception("Stream error", error=str(e))
            yield f"data: [ERROR] {e}\n\n"
        finally:
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
