"""LangChain-based travel itinerary agent using Minimax m2.7."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import AsyncGenerator, Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent
from langchain_openai import ChatOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.rag.retriever import rag_travel_knowledge
from app.agents.tools.geocoding import geocode_place
from app.agents.tools.search import firecrawl_search
from app.agents.tools.weather import get_weather
from app.core.config import settings
from app.core.logging import get_logger
from app.models.chat_itinerary import ChatItinerary
from app.models.chat_message import ChatMessage, MessageSenderRole

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = """You are TravelAI, an expert travel planner with deep knowledge of destinations worldwide.

Your role is to help users plan detailed, personalised travel itineraries. Always:
1. Use `rag_travel_knowledge` first to check the internal knowledge base
2. Use `firecrawl_search` for current info (visa rules, prices, events, safety)
3. Use `geocode_place` for EVERY destination and activity location to get exact coordinates
4. Use `get_weather` for the destination during travel dates if mentioned

When you have gathered sufficient information, generate your final response as natural language followed by a structured itinerary JSON block.

CRITICAL: End EVERY response that contains an itinerary with this exact format:
<itinerary>
{{
  "destination": "<main destination city/country>",
  "total_days": <number>,
  "start_date": "<YYYY-MM-DD or null>",
  "end_date": "<YYYY-MM-DD or null>",
  "weather_summary": "<brief weather note>",
  "best_season": "<best time to visit>",
  "days": [
    {{
      "day": 1,
      "title": "<Day theme>",
      "activities": [
        {{
          "time": "09:00",
          "title": "<Activity name>",
          "description": "<what to do/see>",
          "location": "<full place name>",
          "lat": <latitude as float>,
          "lon": <longitude as float>,
          "duration_hours": <float>,
          "category": "culture|food|nature|transport|accommodation|shopping"
        }}
      ]
    }}
  ],
  "tips": ["<practical tip 1>", "<tip 2>"],
  "estimated_budget": {{
    "currency": "USD",
    "accommodation_per_night": <number or null>,
    "food_per_day": <number or null>,
    "total_estimate": <number or null>
  }}
}}
</itinerary>

Always use real geocoordinates from `geocode_place`. Never make up lat/lon values.
Be conversational and enthusiastic in your main response text before the itinerary block.

Tools available: {tools}
Tool names: {tool_names}

{agent_scratchpad}"""

_HUMAN_TEMPLATE = "{input}"

# ---------------------------------------------------------------------------
# Build tools list
# ---------------------------------------------------------------------------
AGENT_TOOLS = [
    rag_travel_knowledge,
    geocode_place,
    get_weather,
    firecrawl_search,
]


def _build_llm() -> ChatOpenAI:
    """Build Minimax m2.7 LLM via OpenAI-compatible interface."""
    return ChatOpenAI(
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,  # type: ignore[arg-type]
        base_url=settings.LLM_BASE_URL,
        temperature=0.7,
        streaming=True,
    )


def _build_agent_executor():
    """Build a ReAct agent executor using langgraph.prebuilt."""
    llm = _build_llm()

    return create_react_agent(
        model=llm,
        tools=AGENT_TOOLS,
        prompt=_SYSTEM_PROMPT,
    )


def _messages_to_langchain(messages: list[dict[str, Any]]) -> list[BaseMessage]:
    """Convert stored ChatMessage dicts to LangChain message objects."""
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
    """Extract and parse the <itinerary>...</itinerary> JSON block from agent output."""
    match = re.search(r"<itinerary>(.*?)</itinerary>", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(1).strip())
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse itinerary JSON", error=str(e))
        return None


def _strip_itinerary_block(text: str) -> str:
    """Remove the raw <itinerary> XML block from the response text."""
    return re.sub(r"\s*<itinerary>.*?</itinerary>", "", text, flags=re.DOTALL).strip()


# ---------------------------------------------------------------------------
# Main streaming function
# ---------------------------------------------------------------------------
async def run_langchain_agent(
    chat_id: int,
    user_message: str,
    history: list[dict[str, Any]],
    db: AsyncSession,
) -> AsyncGenerator[str, None]:
    """Run the LangChain travel agent and stream tokens.

    Saves the assistant ChatMessage and upserts ChatItinerary on completion.

    Yields:
        SSE-formatted text tokens (raw strings, not SSE wrapped).
    """
    executor = _build_agent_executor()
    chat_history = _messages_to_langchain(history)

    full_response = ""

    try:
        async for event in executor.astream_events(
            {
                "messages": chat_history + [HumanMessage(content=user_message)],
            },
            version="v2",
        ):
            kind = event.get("event", "")

            if kind == "on_chat_model_stream":
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
    # Persist assistant message
    # -----------------------------------------------------------------------
    try:
        clean_response = _strip_itinerary_block(full_response)
        assistant_msg = ChatMessage(
            chat_room_id=chat_id,
            sender_role=MessageSenderRole.assistant,
            content=clean_response,
            message_metadata={"agent": "langchain"},
        )
        db.add(assistant_msg)
        await db.flush()

        # -------------------------------------------------------------------
        # Extract and upsert itinerary
        # -------------------------------------------------------------------
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
                new_itinerary = ChatItinerary(
                    chat_room_id=chat_id,
                    itinerary_data=itinerary_data,
                )
                db.add(new_itinerary)

        await db.commit()
        logger.info(
            "Agent response saved",
            chat_id=chat_id,
            has_itinerary=itinerary_data is not None,
        )

    except Exception as e:
        await db.rollback()
        logger.exception("Failed to save agent response", error=str(e), chat_id=chat_id)
