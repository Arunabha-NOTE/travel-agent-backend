"""LangChain-based travel itinerary agent — multi-step planning flow."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.prompts import MAIN_SYSTEM_PROMPT
from app.agents.rag.retriever import rag_travel_knowledge
from app.agents.tools.geocoding import geocode_place
from app.agents.tools.search import firecrawl_search
from app.agents.tools.travel import (
    get_airport_transit,
    get_place_details,
    search_flights,
    search_hotels,
)
from app.agents.tools.weather import get_weather
from app.core.config import settings
from app.core.logging import get_logger
from app.models.chat_itinerary import ChatItinerary
from app.models.chat_message import ChatMessage, MessageSenderRole
from app.models.planning_session import DEFAULT_PREFERENCES, PlanningSession

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# All tools
# ---------------------------------------------------------------------------
AGENT_TOOLS = [
    # Planning-stage tools
    search_flights,
    get_airport_transit,
    search_hotels,
    get_place_details,
    # General research
    rag_travel_knowledge,
    firecrawl_search,
    # Logistics
    geocode_place,
    get_weather,
]


def _build_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,  # type: ignore[arg-type]
        base_url=settings.LLM_BASE_URL,
        temperature=0.7,
        streaming=True,
    )


def _build_agent_executor(dynamic_prompt: str = ""):
    llm = _build_llm()
    final_prompt = MAIN_SYSTEM_PROMPT
    if dynamic_prompt:
        final_prompt += f"\n\n{dynamic_prompt}"
    return create_react_agent(model=llm, tools=AGENT_TOOLS, prompt=final_prompt)


def _messages_to_langchain(messages: list[dict[str, Any]]) -> list[BaseMessage]:
    result = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "user":
            result.append(HumanMessage(content=content))
        elif role == "assistant":
            result.append(AIMessage(content=content))
        elif role == "system":
            result.append(SystemMessage(content=content))
    return result


def _extract_itinerary(text: str) -> dict | None:
    match = re.search(r"<itinerary>(.*?)</itinerary>", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(1).strip())
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse itinerary JSON", error=str(e))
        return None


def _extract_planning_stage(text: str) -> str | None:
    """Extract <planning_stage>value</planning_stage> from agent output."""
    match = re.search(r"<planning_stage>(.*?)</planning_stage>", text, re.DOTALL)
    return match.group(1).strip() if match else None


def _strip_agent_tags(text: str) -> str:
    """Remove <itinerary> and <planning_stage> XML blocks from stored response text."""
    text = re.sub(r"\s*<itinerary>.*?</itinerary>", "", text, flags=re.DOTALL)
    text = re.sub(r"\s*<planning_stage>.*?</planning_stage>", "", text, flags=re.DOTALL)
    return text.strip()


# ---------------------------------------------------------------------------
# Main streaming function
# ---------------------------------------------------------------------------


async def run_langchain_agent(
    chat_id: uuid.UUID,
    user_message: str,
    history: list[dict[str, Any]],
    db: AsyncSession,
) -> AsyncGenerator[str, None]:
    """Run the multi-step LangChain travel agent and stream tokens.

    Saves the assistant ChatMessage, upserts ChatItinerary, and updates
    PlanningSession stage on each turn.

    Yields:
        SSE-formatted text tokens, including [STEP:...] tool-call events.
    """
    # Extract dynamic system context (itinerary + planning session) from history
    dynamic_sys_prompt = ""
    if history and history[0].get("role") == "system":
        dynamic_sys_prompt = history.pop(0).get("content", "")

    executor = _build_agent_executor(dynamic_sys_prompt)
    chat_history = _messages_to_langchain(history)

    full_response = ""

    try:
        async for event in executor.astream_events(
            {"messages": chat_history + [HumanMessage(content=user_message)]},
            version="v2",
        ):
            kind = event.get("event", "")

            # Stream tool call starts as [STEP:] markers for the UI
            if kind == "on_tool_start":
                tool_name = event.get("name", "")
                tool_input = event.get("data", {}).get("input", {})
                step_label = _tool_step_label(tool_name, tool_input)
                step_token = f"[STEP:{step_label}]"
                full_response += step_token
                yield step_token

            # Stream LLM text tokens
            elif kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    token = chunk.content
                    full_response += token
                    yield token

    except Exception as e:
        error_msg = f"\n\n*An error occurred: {e}*"
        full_response += error_msg
        yield error_msg
        logger.exception("LangChain agent error", error=str(e), chat_id=chat_id)

    # -----------------------------------------------------------------------
    # Persist assistant message + itinerary + planning stage
    # -----------------------------------------------------------------------
    try:
        # Strip XML tags for stored message (UI already handles them)
        clean_response = _strip_agent_tags(full_response)
        # Also strip [STEP:] markers from stored message
        clean_response = re.sub(r"\[STEP:[^\]]*\]", "", clean_response).strip()

        assistant_msg = ChatMessage(
            chat_room_id=chat_id,
            sender_role=MessageSenderRole.assistant,
            content=clean_response,
            message_metadata={"agent": "langchain"},
        )
        db.add(assistant_msg)
        await db.flush()

        # Update itinerary
        itinerary_data = _extract_itinerary(full_response)
        if itinerary_data:
            existing = await db.execute(
                select(ChatItinerary).where(ChatItinerary.chat_room_id == chat_id)
            )
            existing_row = existing.scalars().first()
            if existing_row:
                existing_row.itinerary_data = itinerary_data
                existing_row.updated_at = datetime.now(timezone.utc)
            else:
                db.add(
                    ChatItinerary(chat_room_id=chat_id, itinerary_data=itinerary_data)
                )

        # Update planning session stage
        new_stage = _extract_planning_stage(full_response)
        if new_stage:
            await _upsert_planning_stage(db, chat_id, new_stage)

        await db.commit()
        logger.info(
            "Agent response saved",
            chat_id=chat_id,
            has_itinerary=itinerary_data is not None,
            stage=new_stage,
        )

    except Exception as e:
        await db.rollback()
        logger.exception("Failed to save agent response", error=str(e), chat_id=chat_id)


async def _upsert_planning_stage(
    db: AsyncSession, chat_id: uuid.UUID, new_stage: str
) -> None:
    """Create or update the PlanningSession stage."""
    result = await db.execute(
        select(PlanningSession).where(PlanningSession.chat_room_id == chat_id)
    )
    session = result.scalars().first()
    if session:
        session.stage = new_stage
        session.updated_at = datetime.now(timezone.utc)
    else:
        db.add(
            PlanningSession(
                chat_room_id=chat_id,
                stage=new_stage,
                preferences=dict(DEFAULT_PREFERENCES),
            )
        )


def _tool_step_label(tool_name: str, tool_input: dict) -> str:
    """Map tool names to human-readable step labels for the UI."""
    labels = {
        "search_flights": lambda i: f"✈️ Searching flights {i.get('origin_city', '')} → {i.get('destination_city', '')}...",
        "get_airport_transit": lambda i: f"🛫 Checking terminal transit at {i.get('airport_name', '')}...",
        "search_hotels": lambda i: f"🏨 Finding hotels in {i.get('destination', '')}...",
        "get_place_details": lambda i: f"📍 Getting details for {i.get('place_name', '')}...",
        "firecrawl_search": lambda i: f"🔍 Searching: {i.get('query', '')[:50]}...",
        "geocode_place": lambda i: f"📍 Locating {i.get('place_name', '')}...",
        "get_weather": lambda i: "🌤️ Checking weather forecast...",
        "rag_travel_knowledge": lambda i: f"📚 Checking knowledge base for {i.get('query', '')[:40]}...",
    }
    fn = labels.get(tool_name)
    if fn:
        try:
            return fn(tool_input)
        except Exception:
            pass
    return f"🔧 Using {tool_name}..."
