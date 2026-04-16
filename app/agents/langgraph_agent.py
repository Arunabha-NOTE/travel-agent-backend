"""LangGraph-based travel itinerary agent — staged planning state machine."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, AsyncGenerator, Sequence, TypedDict
import operator

from langchain_core.messages import BaseMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import create_react_agent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.prompts import (
    ATTRACTION_AGENT_PROMPT,
    FLIGHT_AGENT_PROMPT,
    HOTEL_AGENT_PROMPT,
    PLANNER_AGENT_PROMPT,
)
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
from app.agents.langchain_agent import (
    _extract_itinerary,
    _extract_planning_stage,
    _messages_to_langchain,
    _strip_agent_tags,
    _tool_step_label,
    _upsert_planning_stage,
)
from app.core.config import settings
from app.core.logging import get_logger
from app.models.chat_itinerary import ChatItinerary
from app.models.chat_message import ChatMessage, MessageSenderRole
from app.models.planning_session import PlanningSession

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class TravelPlanState(TypedDict):
    """State shared across all nodes in the travel planning graph."""

    messages: Annotated[Sequence[BaseMessage], operator.add]
    stage: str  # current planning stage
    context: str  # dynamic system context (itinerary + planning prefs)


# ---------------------------------------------------------------------------
# LLM factory
# ---------------------------------------------------------------------------


def _build_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,  # type: ignore[arg-type]
        base_url=settings.LLM_BASE_URL,
        temperature=0.7,
        streaming=True,
        max_retries=2,
    )


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_langgraph_agent(stage: str = "initial", context: str = "") -> Any:
    """Build the staged LangGraph travel planning state machine.

    The graph routes to a specialised sub-agent based on the current
    planning stage, avoiding redundant work at each turn.
    """
    llm = _build_llm()
    ctx_suffix = f"\n\n{context}" if context else ""

    # -- Sub-agents, each specialised for one planning stage --

    gathering_agent = create_react_agent(
        model=llm,
        tools=[rag_travel_knowledge, firecrawl_search, get_weather],
        prompt=(
            "You are TravelAI. A user wants to plan a trip. "
            "Ask warmly about: budget (total or per-person + currency), "
            "group size (adults + children), travel dates, and any hard constraints. "
            "Do NOT suggest flights or hotels yet. Gather info only. "
            "End with: <planning_stage>initial</planning_stage>" + ctx_suffix
        ),
    )

    flight_agent = create_react_agent(
        model=llm,
        tools=[search_flights, get_airport_transit, firecrawl_search, get_weather],
        prompt=FLIGHT_AGENT_PROMPT + ctx_suffix,
    )

    hotel_agent = create_react_agent(
        model=llm,
        tools=[search_hotels, firecrawl_search, geocode_place],
        prompt=HOTEL_AGENT_PROMPT + ctx_suffix,
    )

    attraction_agent = create_react_agent(
        model=llm,
        tools=[rag_travel_knowledge, firecrawl_search, get_weather, get_place_details],
        prompt=ATTRACTION_AGENT_PROMPT + ctx_suffix,
    )

    planner_agent = create_react_agent(
        model=llm,
        tools=[geocode_place, get_place_details, get_weather],
        prompt=PLANNER_AGENT_PROMPT + ctx_suffix,
    )

    # -- Node wrappers that inject state and return only new messages --

    async def _run_subagent(agent: Any, state: TravelPlanState) -> dict:
        result = await agent.ainvoke({"messages": list(state["messages"])})
        new_msgs = result["messages"][len(state["messages"]) :]
        return {"messages": new_msgs}

    async def gathering_node(state: TravelPlanState) -> dict:
        return await _run_subagent(gathering_agent, state)

    async def flight_node(state: TravelPlanState) -> dict:
        return await _run_subagent(flight_agent, state)

    async def hotel_node(state: TravelPlanState) -> dict:
        return await _run_subagent(hotel_agent, state)

    async def attraction_node(state: TravelPlanState) -> dict:
        return await _run_subagent(attraction_agent, state)

    async def planner_node(state: TravelPlanState) -> dict:
        return await _run_subagent(planner_agent, state)

    # -- Router: decides which node to activate based on stage --

    def route_by_stage(state: TravelPlanState) -> str:
        s = state.get("stage", "initial")
        routing = {
            "initial": "gather",
            "flights": "flights",
            "hotels": "hotels",
            "attractions": "attractions",
            "complete": "planner",
        }
        return routing.get(s, "gather")

    # -- Build graph --

    workflow = StateGraph(TravelPlanState)

    workflow.add_node("gather", gathering_node)
    workflow.add_node("flights", flight_node)
    workflow.add_node("hotels", hotel_node)
    workflow.add_node("attractions", attraction_node)
    workflow.add_node("planner", planner_node)

    workflow.add_conditional_edges(START, route_by_stage)

    for node in ["gather", "flights", "hotels", "attractions", "planner"]:
        workflow.add_edge(node, END)

    return workflow.compile()


# ---------------------------------------------------------------------------
# Main streaming function
# ---------------------------------------------------------------------------


async def run_langgraph_agent(
    chat_id: uuid.UUID,
    user_message: str,
    history: list[dict[str, Any]],
    db: AsyncSession,
) -> AsyncGenerator[str, None]:
    """Run the staged LangGraph travel agent and stream tokens.

    Saves the assistant ChatMessage, upserts ChatItinerary, and updates
    PlanningSession stage on each turn.

    Yields:
        Text tokens and [STEP:...] markers for tool-call UI indicators.
    """
    # Extract dynamic context from history (injected by messages.py)
    dynamic_context = ""
    if history and history[0].get("role") == "system":
        dynamic_context = history.pop(0).get("content", "")

    # Load current planning stage from DB
    stage = await _load_stage(db, chat_id)

    graph = build_langgraph_agent(stage=stage, context=dynamic_context)
    chat_history = _messages_to_langchain(history)
    chat_history.append(HumanMessage(content=user_message))

    full_response = ""

    try:
        async for event in graph.astream_events(
            {"messages": chat_history, "stage": stage, "context": dynamic_context},
            version="v2",
        ):
            kind = event.get("event", "")

            # Emit tool step markers
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
        error_msg = f"\n\n*An error occurred in LangGraph: {e}*"
        full_response += error_msg
        yield error_msg
        logger.exception("LangGraph agent error", error=str(e), chat_id=chat_id)

    # -----------------------------------------------------------------------
    # Persist assistant message + itinerary + stage
    # -----------------------------------------------------------------------
    try:
        clean_response = _strip_agent_tags(full_response)
        clean_response = re.sub(r"\[STEP:[^\]]*\]", "", clean_response).strip()

        assistant_msg = ChatMessage(
            chat_room_id=chat_id,
            sender_role=MessageSenderRole.assistant,
            content=clean_response,
            message_metadata={"agent": "langgraph"},
        )
        db.add(assistant_msg)
        await db.flush()

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

        new_stage = _extract_planning_stage(full_response)
        if new_stage:
            await _upsert_planning_stage(db, chat_id, new_stage)

        await db.commit()
        logger.info(
            "LangGraph agent response saved",
            chat_id=chat_id,
            has_itinerary=itinerary_data is not None,
            stage=new_stage,
        )

    except Exception as e:
        await db.rollback()
        logger.exception(
            "Failed to save LangGraph agent response", error=str(e), chat_id=chat_id
        )


async def _load_stage(db: AsyncSession, chat_id: uuid.UUID) -> str:
    """Load the current planning stage for a chat room."""
    result = await db.execute(
        select(PlanningSession).where(PlanningSession.chat_room_id == chat_id)
    )
    session = result.scalars().first()
    return session.stage if session else "initial"
