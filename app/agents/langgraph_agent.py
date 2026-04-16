"""LangGraph-based travel itinerary agent using minmax m2.7."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import AsyncGenerator, Any, Sequence, Annotated, TypedDict
import operator
import uuid


from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import create_react_agent

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
from app.agents.langchain_agent import (
    _messages_to_langchain,
    _extract_itinerary,
    _strip_itinerary_block,
)
from app.agents.prompts import RESEARCH_PROMPT, LOGISTICS_PROMPT, PLANNER_PROMPT

logger = get_logger(__name__)

AGENT_TOOLS = [
    rag_travel_knowledge,
    geocode_place,
    get_weather,
    firecrawl_search,
]


def _should_retry(exc: BaseException) -> bool:
    """Retry on transient 529/500 server errors from Minimax."""
    msg = str(exc).lower()
    return "529" in msg or "overloaded" in msg or "500" in msg or "rate" in msg


def _build_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,  # type: ignore[arg-type]
        base_url=settings.LLM_BASE_URL,
        temperature=0.7,
        streaming=True,
        max_retries=2,  # built-in openai-sdk retries
    )


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]


def build_langgraph_agent(dynamic_prompt: str = ""):
    """Build the LangGraph travel agent state machine."""

    llm = _build_llm()

    # Prepend dynamic prompt to base prompts if provided
    research_p = (
        RESEARCH_PROMPT + f"\n\n{dynamic_prompt}" if dynamic_prompt else RESEARCH_PROMPT
    )
    logistics_p = (
        LOGISTICS_PROMPT + f"\n\n{dynamic_prompt}"
        if dynamic_prompt
        else LOGISTICS_PROMPT
    )
    planner_p = (
        PLANNER_PROMPT + f"\n\n{dynamic_prompt}" if dynamic_prompt else PLANNER_PROMPT
    )

    # 1. Sub-agents using create_react_agent
    research_agent = create_react_agent(
        model=llm,
        tools=[rag_travel_knowledge, firecrawl_search],
        prompt=research_p,
    )

    logistics_agent = create_react_agent(
        model=llm, tools=[geocode_place, get_weather], prompt=logistics_p
    )

    # 2. Node wrappers that only append NEW messages to parent state
    async def research_node(state: AgentState):
        result = await research_agent.ainvoke({"messages": state["messages"]})
        return {"messages": result["messages"][len(state["messages"]) :]}

    async def logistics_node(state: AgentState):
        result = await logistics_agent.ainvoke({"messages": state["messages"]})
        return {"messages": result["messages"][len(state["messages"]) :]}

    async def planner_node(state: AgentState):
        system_msg = SystemMessage(content=planner_p)
        # Planner doesn't need tools, just compiles the final itinerary
        response = await llm.ainvoke([system_msg] + list(state["messages"]))
        return {"messages": [response]}

    # 3. Build sequential parent graph
    workflow = StateGraph(AgentState)

    workflow.add_node("research", research_node)
    workflow.add_node("logistics", logistics_node)
    workflow.add_node("planner", planner_node)

    workflow.add_edge(START, "research")
    workflow.add_edge("research", "logistics")
    workflow.add_edge("logistics", "planner")
    workflow.add_edge("planner", END)

    return workflow.compile()


async def run_langgraph_agent(
    chat_id: uuid.UUID,
    user_message: str,
    history: list[dict[str, Any]],
    db: AsyncSession,
) -> AsyncGenerator[str, None]:
    """Run the LangGraph travel agent and stream tokens.

    Similar to run_langchain_agent but uses the state-machine graph structure.
    Saves the assistant ChatMessage and upserts ChatItinerary on completion.
    """

    # Extract dynamic system prompt from history if present
    dynamic_sys_prompt = ""
    if history and history[0].get("role") == "system":
        dynamic_sys_prompt = history.pop(0).get("content", "")

    graph = build_langgraph_agent(dynamic_sys_prompt)
    chat_history = _messages_to_langchain(history)

    # Append the newest user message
    chat_history.append(HumanMessage(content=user_message))

    full_response = ""

    try:
        # Stream events across all nodes
        async for event in graph.astream_events(
            {"messages": chat_history}, version="v2"
        ):
            kind = event.get("event", "")

            # We stream only from the underlying chat model to mimic ReAct behavior
            if kind == "on_chat_model_stream":
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
    # Persist assistant message
    # -----------------------------------------------------------------------
    try:
        clean_response = _strip_itinerary_block(full_response)
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
                new_itinerary = ChatItinerary(
                    chat_room_id=chat_id,
                    itinerary_data=itinerary_data,
                )
                db.add(new_itinerary)

        await db.commit()
        logger.info(
            "LangGraph agent response saved",
            chat_id=chat_id,
            has_itinerary=itinerary_data is not None,
        )

    except Exception as e:
        await db.rollback()
        logger.exception(
            "Failed to save LangGraph agent response", error=str(e), chat_id=chat_id
        )
