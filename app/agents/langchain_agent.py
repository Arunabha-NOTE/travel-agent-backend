"""LangChain-based travel itinerary agent using Minimax m2.7."""

from __future__ import annotations

import json
import re
import uuid
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
_SYSTEM_PROMPT = """You are TravelAI, an expert AI travel planner. Your job is to maintain and continuously refine a living travel itinerary throughout the entire conversation.

## Core Behaviour
- **ALWAYS output an <itinerary> block at the end of EVERY response** — even for follow-up questions, clarifications, or short answers.
- If the user hasn't specified a destination yet, make reasonable assumptions and ask for confirmation.
- Each response should UPDATE the itinerary based on all new information learned in this message.
- If the existing itinerary from context is provided, incorporate it and refine it — never start from scratch unless explicitly asked.

## Research Tools (use in this order for every travel response)
1. `rag_travel_knowledge` — check internal knowledge base first
2. `firecrawl_search` — find current visa rules, prices, events, safety info
3. `geocode_place` — get exact lat/lon for EVERY activity location
4. `get_weather` — check weather if travel dates are mentioned or can be inferred

## Itinerary Rules
- Include ALL days, even for short Q&A responses — copy existing days and only modify what changed
- Use real geocoordinates from `geocode_place` for every activity — never make up lat/lon
- For follow-up messages (e.g. "add a museum visit", "change budget", "include flights"), update the relevant parts and re-emit the full updated itinerary

## MANDATORY: End EVERY single response with this exact XML block:
<itinerary>
{{
  "destination": "<main destination>",
  "total_days": <number>,
  "start_date": "<YYYY-MM-DD or null>",
  "end_date": "<YYYY-MM-DD or null>",
  "weather_summary": "<brief weather note or null>",
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

Be warm, enthusiastic, and conversational in your main response text. The itinerary block is always silent — the UI renders it automatically."""

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


def _build_agent_executor(dynamic_prompt: str = ""):
    """Build a ReAct agent executor using langgraph.prebuilt."""
    llm = _build_llm()

    final_prompt = _SYSTEM_PROMPT
    if dynamic_prompt:
        final_prompt += f"\n\n{dynamic_prompt}"

    return create_react_agent(
        model=llm,
        tools=AGENT_TOOLS,
        prompt=final_prompt,
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
    chat_id: uuid.UUID,
    user_message: str,
    history: list[dict[str, Any]],
    db: AsyncSession,
) -> AsyncGenerator[str, None]:
    """Run the LangChain travel agent and stream tokens.

    Saves the assistant ChatMessage and upserts ChatItinerary on completion.

    Yields:
        SSE-formatted text tokens (raw strings, not SSE wrapped).
    """

    # Extract dynamic system prompt from history if present
    dynamic_sys_prompt = ""
    if history and history[0].get("role") == "system":
        dynamic_sys_prompt = history.pop(0).get("content", "")

    executor = _build_agent_executor(dynamic_sys_prompt)
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
