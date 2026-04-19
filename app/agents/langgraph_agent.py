"""LangGraph-based travel itinerary agent — Sophisticated Planner-Reflector architecture."""

from __future__ import annotations

import json
import re
import uuid
from typing import Annotated, Any, AsyncGenerator, Sequence, TypedDict, Literal
import operator

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import START, StateGraph
from langgraph.prebuilt import ToolNode
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.prompts import (
    ATTRACTION_AGENT_PROMPT,
    FLIGHT_AGENT_PROMPT,
    HOTEL_AGENT_PROMPT,
    PLANNER_AGENT_PROMPT,
    REFLECTOR_PROMPT,
    MAIN_SYSTEM_PROMPT,
)
from app.agents.tool_suite import AGENT_TOOLS
from app.agents.langchain_agent import (
    _clean_stage_value,
    _extract_itinerary,
    _extract_itinerary_tool_snapshot,
    _extract_planning_stage,
    _inject_panel_state,
    _is_finalize_request,
    _recover_itinerary_snapshot,
    _build_enforced_preflight_context,
    _normalize_itinerary_for_ui,
    _infer_destination_hint,
    _message_content_to_text,
    _messages_to_langchain,
    _load_progress_state,
    _persist_progress_snapshot,
    _should_attempt_itinerary_repair,
    _strip_agent_tags,
    _itinerary_signature,
    _tool_step_label,
    _upsert_itinerary,
    _upsert_planning_stage,
)
from app.core.config import settings
from app.core.logging import get_logger
from app.models.chat_message import ChatMessage, MessageSenderRole

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class TravelPlanState(TypedDict):
    """Deeply stateful representation for the Planner-Reflector loop."""

    messages: Annotated[Sequence[BaseMessage], operator.add]
    stage: str
    reflection_count: int
    is_valid: bool
    context: str  # dynamic system context
    latest_reflection: str | None


# ---------------------------------------------------------------------------
# LLM & Tools
# ---------------------------------------------------------------------------


def _build_llm(streaming: bool = True) -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,  # type: ignore[arg-type]
        base_url=settings.LLM_BASE_URL,
        temperature=0.7,
        streaming=streaming,
        max_retries=2,
        max_tokens=8192,
    )


TOOLS = AGENT_TOOLS

# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


async def planner_node(state: TravelPlanState) -> dict:
    """The main 'brain' that decides whether to use tools or answer."""
    llm = _build_llm().bind_tools(TOOLS)

    stage = state.get("stage", "initial")
    ctx = state.get("context", "")

    # Select stage-specific prompt prefix
    stage_prompts = {
        "initial": "Ask about budget, group size, dates, and memberships. DO NOT suggest flights yet.",
        "flights": FLIGHT_AGENT_PROMPT,
        "hotels": HOTEL_AGENT_PROMPT,
        "attractions": ATTRACTION_AGENT_PROMPT,
        "complete": PLANNER_AGENT_PROMPT,
    }

    system_instruction = f"{MAIN_SYSTEM_PROMPT}\n\nCURRENT STAGE DUTY: {stage_prompts.get(stage, stage_prompts['initial'])}\n\n{ctx}"

    # If we are in a reflection loop, inject the feedback
    messages = list(state["messages"])
    if state.get("latest_reflection"):
        messages.append(
            SystemMessage(
                content=f"CRITICAL FEEDBACK FROM QC: {state['latest_reflection']}\nPlease correct your previous response based on this feedback."
            )
        )

    # We prefix with the full system prompt for every planner turn
    full_messages = [SystemMessage(content=system_instruction)] + messages

    response = await llm.ainvoke(full_messages)
    return {"messages": [response]}


async def reflector_node(state: TravelPlanState) -> dict:
    """Evaluates the planner's output against the concierge standards."""
    llm = _build_llm(streaming=False)  # No need for streaming in reflection

    last_message = state["messages"][-1]
    if not isinstance(last_message, AIMessage):
        return {"is_valid": True, "latest_reflection": None}

    # Some providers reject empty chat content payloads; skip reflection when
    # the planner output has no textual content.
    last_content = _message_content_to_text(last_message.content).strip()
    if not last_content:
        return {"is_valid": True, "latest_reflection": None}

    # Provider occasionally rejects very large reflector payloads with
    # misleading "content is empty" errors. Use heuristic pass/fail in that case.
    if len(last_content) > 14_000:
        fallback_valid = bool(_extract_planning_stage(last_content))
        if state.get("stage") == "complete":
            fallback_valid = (
                _extract_itinerary(last_content, log_on_failure=False) is not None
            )
        logger.warning(
            "LangGraph reflection skipped due oversized planner payload",
            stage=state.get("stage", "unknown"),
            planner_content_len=len(last_content),
            fallback_valid=fallback_valid,
        )
        return {
            "is_valid": fallback_valid,
            "latest_reflection": None,
            "reflection_count": state.get("reflection_count", 0)
            + (0 if fallback_valid else 1),
        }

    # We ask the reflector to judge the last AI message
    prompt = (
        f"{REFLECTOR_PROMPT or 'Review the planner output for correctness and completeness.'}\n\n"
        f"PLANNER OUTPUT TO REVIEW:\n{last_content}\n\n"
        f"CURRENT STAGE: {state['stage']}"
    )

    if not prompt.strip():
        return {"is_valid": True, "latest_reflection": None}

    try:
        response = await llm.ainvoke([SystemMessage(content=prompt)])
    except Exception as exc:
        err = str(exc)
        # Some providers intermittently reject reflector prompts as empty;
        # treat reflection as pass-through so tool execution does not fail.
        if "chat content is empty" in err.lower() or "invalid params" in err.lower():
            fallback_valid = bool(_extract_planning_stage(last_content))
            if state.get("stage") == "complete":
                fallback_valid = (
                    _extract_itinerary(last_content, log_on_failure=False) is not None
                )
            logger.warning(
                "LangGraph reflection skipped due provider empty-content rejection",
                error=err,
                stage=state.get("stage", "unknown"),
                planner_content_len=len(last_content),
                fallback_valid=fallback_valid,
            )
            return {
                "is_valid": fallback_valid,
                "latest_reflection": None,
                "reflection_count": state.get("reflection_count", 0)
                + (0 if fallback_valid else 1),
            }
        raise
    decision = str(response.content).strip()

    is_valid = "VALID" in decision.upper()
    feedback = None if is_valid else decision

    logger.info("LangGraph Reflection result", is_valid=is_valid, feedback=feedback)

    return {
        "is_valid": is_valid,
        "latest_reflection": feedback,
        "reflection_count": state.get("reflection_count", 0) + (0 if is_valid else 1),
    }


# Custom tool execution wrapper
tool_executor = ToolNode(TOOLS)

# ---------------------------------------------------------------------------
# Conditional Edges
# ---------------------------------------------------------------------------


def route_planner(state: TravelPlanState) -> Literal["tools", "reflector"]:
    """Routes to tools if needed, otherwise to reflection."""
    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"
    return "reflector"


def route_reflector(state: TravelPlanState) -> Literal["planner", "__end__"]:
    """Decides if we need a retry or if we're done."""
    if state.get("is_valid") or state.get("reflection_count", 0) >= 2:
        return "__end__"
    return "planner"


# ---------------------------------------------------------------------------
# Graph Builder
# ---------------------------------------------------------------------------


def build_langgraph_agent() -> Any:
    workflow = StateGraph(TravelPlanState)

    workflow.add_node("planner", planner_node)
    workflow.add_node("tools", tool_executor)
    workflow.add_node("reflector", reflector_node)

    workflow.add_edge(START, "planner")
    workflow.add_conditional_edges("planner", route_planner)
    workflow.add_edge("tools", "planner")
    workflow.add_conditional_edges("reflector", route_reflector)

    return workflow.compile()


# ---------------------------------------------------------------------------
# Run function
# ---------------------------------------------------------------------------


async def run_langgraph_agent(
    chat_id: uuid.UUID,
    user_message: str,
    history: list[dict[str, Any]],
    db: AsyncSession,
) -> AsyncGenerator[str, None]:
    # Extract dynamic context
    dynamic_context = ""
    if history and history[0].get("role") == "system":
        dynamic_context = history.pop(0).get("content", "")

    (
        last_persisted_stage,
        last_persisted_itinerary_signature,
    ) = await _load_progress_state(db, chat_id)
    preflight_context = await _build_enforced_preflight_context(
        user_message=user_message,
        dynamic_context=dynamic_context,
        stage=last_persisted_stage,
    )
    if preflight_context:
        dynamic_context = (
            f"{dynamic_context}\n\n---\n\n{preflight_context}"
            if dynamic_context
            else preflight_context
        )
    stage = last_persisted_stage or "initial"
    graph = build_langgraph_agent()
    chat_history = _messages_to_langchain(history)
    chat_history.append(HumanMessage(content=user_message))

    full_response = ""
    last_message_content = ""
    planner_candidates: list[str] = []
    itinerary_data = None
    pending_tool_snapshot: tuple[dict[str, Any], str | None, int | None] | None = None
    yielded_preflight_steps: set[str] = set()

    def _score_candidate(text: str) -> int:
        if not text:
            return -10_000

        score = len(text) // 200
        lowered = text.lower()
        if "<itinerary>" in lowered:
            score += 200
        if "```json" in lowered:
            score += 120
        if re.search(r'"destination"\s*:', text):
            score += 90
        if re.search(r'"days"\s*:', text):
            score += 90
        if re.search(r"day\s+\d+", lowered):
            score += 40
        if "<think>" in lowered:
            score -= 15
        if "saving itinerary details" in lowered:
            score += 10
        return score

    def _pick_final_text(*texts: str) -> str:
        best_text = ""
        best_score = -10_000
        for text in texts:
            candidate = (text or "").strip()
            if not candidate:
                continue
            score = _score_candidate(candidate)
            if score > best_score:
                best_text = candidate
                best_score = score
        return best_text

    try:
        for step_token in [
            "[STEP:🕒 Synchronizing clock...]",
            "[STEP:📚 Checking knowledge base for current travel context...]",
        ]:
            if step_token not in yielded_preflight_steps:
                yielded_preflight_steps.add(step_token)
                yield step_token

        async for event in graph.astream_events(
            {
                "messages": chat_history,
                "stage": stage,
                "context": dynamic_context,
                "reflection_count": 0,
                "is_valid": False,
                "latest_reflection": None,
            },
            version="v2",
        ):
            kind = event.get("event", "")
            metadata = event.get("metadata", {})
            node_name = metadata.get("langgraph_node", "")

            # Tool markers
            if kind == "on_tool_start":
                tool_name = event.get("name", "")
                tool_input = event.get("data", {}).get("input", {})
                step_label = _tool_step_label(tool_name, tool_input)
                step_token = f"[STEP:{step_label}]"
                yield step_token

                if tool_name == "update_itinerary_panel":
                    (
                        tool_itinerary,
                        tool_stage,
                        tool_expected_days,
                    ) = _extract_itinerary_tool_snapshot(tool_input)
                    if tool_itinerary is not None:
                        pending_tool_snapshot = (
                            tool_itinerary,
                            tool_stage,
                            tool_expected_days,
                        )

            elif kind == "on_tool_end":
                tool_name = event.get("name", "")
                tool_output = event.get("data", {}).get("output")
                if tool_name == "update_itinerary_panel" and pending_tool_snapshot:
                    try:
                        (
                            tool_itinerary,
                            tool_stage,
                            tool_expected_days,
                        ) = pending_tool_snapshot

                        output_text = _message_content_to_text(tool_output)
                        if output_text.strip().startswith("{"):
                            try:
                                parsed_tool_output = json.loads(output_text)
                                tool_stage = (
                                    _clean_stage_value(parsed_tool_output.get("stage"))
                                    or tool_stage
                                )
                            except json.JSONDecodeError:
                                pass

                        tool_snapshot = _inject_panel_state(
                            tool_itinerary,
                            stage=tool_stage,
                            expected_total_days=tool_expected_days,
                            source="update_itinerary_panel",
                            status="captured",
                        )
                        itinerary_data = tool_snapshot

                        (
                            last_persisted_stage,
                            last_persisted_itinerary_signature,
                            normalized_snapshot,
                            wrote_progress,
                        ) = await _persist_progress_snapshot(
                            db,
                            chat_id,
                            parsed_stage=tool_stage,
                            parsed_itinerary=tool_snapshot,
                            destination_hint=_infer_destination_hint(
                                dynamic_context,
                                json.dumps(tool_itinerary, default=str)[:2000],
                                user_message,
                            ),
                            context_text="\n".join(
                                [
                                    dynamic_context,
                                    user_message,
                                    json.dumps(tool_itinerary, default=str)[:6000],
                                ]
                            ),
                            last_stage=last_persisted_stage,
                            last_itinerary_signature=last_persisted_itinerary_signature,
                        )
                        if normalized_snapshot:
                            itinerary_data = normalized_snapshot
                        if wrote_progress:
                            logger.info(
                                "Structured itinerary snapshot persisted (langgraph)",
                                chat_id=chat_id,
                                stage=last_persisted_stage,
                                itinerary_signature=last_persisted_itinerary_signature,
                            )
                    except Exception as snapshot_err:
                        await db.rollback()
                        logger.warning(
                            "Failed to persist structured itinerary tool snapshot (langgraph)",
                            chat_id=chat_id,
                            error=str(snapshot_err),
                        )
                    finally:
                        pending_tool_snapshot = None

            # LLM Streaming tokens
            elif kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    token = chunk.content
                    full_response += token
                    # Yield tokens to UI. We prioritize showing SOMETHING over showing nothing.
                    if not node_name or "planner" in node_name:
                        yield token

            # Capture the final AI message content and try to extract itinerary
            elif kind == "on_chat_model_end":
                output = event.get("data", {}).get("output")
                if output and hasattr(output, "content") and output.content:
                    content = _message_content_to_text(output.content)
                    # If this node is the planner, it becomes our main response
                    if not node_name or "planner" in node_name:
                        last_message_content = content
                        planner_candidates.append(content)

                    # Proactively check for itinerary in ANY message (safety backup)
                    maybe_stage = _extract_planning_stage(content)
                    maybe_itinerary = _extract_itinerary(content, log_on_failure=False)
                    if maybe_itinerary is None and _should_attempt_itinerary_repair(
                        content,
                        parsed_stage=maybe_stage,
                        is_finalize_turn=False,
                    ):
                        maybe_itinerary = await _recover_itinerary_snapshot(
                            source_text=content,
                            history=history,
                            user_message=user_message,
                            dynamic_context=dynamic_context,
                            parsed_stage=maybe_stage,
                            is_finalize_turn=False,
                            allow_minimal_fallback=False,
                        )
                    if maybe_itinerary:
                        logger.info(
                            "LangGraph itinerary found in event stream", node=node_name
                        )
                        itinerary_data = maybe_itinerary

                    if maybe_stage or maybe_itinerary:
                        try:
                            (
                                last_persisted_stage,
                                last_persisted_itinerary_signature,
                                normalized_snapshot,
                                wrote_progress,
                            ) = await _persist_progress_snapshot(
                                db,
                                chat_id,
                                parsed_stage=maybe_stage,
                                parsed_itinerary=maybe_itinerary,
                                destination_hint=_infer_destination_hint(
                                    dynamic_context,
                                    content,
                                    user_message,
                                ),
                                context_text="\n".join(
                                    [dynamic_context, user_message, content]
                                ),
                                last_stage=last_persisted_stage,
                                last_itinerary_signature=last_persisted_itinerary_signature,
                            )
                            if normalized_snapshot:
                                itinerary_data = normalized_snapshot
                            if wrote_progress:
                                logger.info(
                                    "Progress snapshot persisted (langgraph)",
                                    chat_id=chat_id,
                                    stage=last_persisted_stage,
                                    itinerary_signature=last_persisted_itinerary_signature,
                                )
                        except Exception as progress_err:
                            await db.rollback()
                            logger.warning(
                                "Failed progressive itinerary persistence (langgraph)",
                                chat_id=chat_id,
                                error=str(progress_err),
                            )

    except Exception as e:
        error_msg = f"\n\n*An error occurred in LangGraph: {e}*"
        yield error_msg
        logger.exception("LangGraph agent error", error=str(e), chat_id=chat_id)

    # Persist
    try:
        is_finalize_turn = _is_finalize_request(user_message)

        # Use the content of the LAST planner run.
        # Fallback to full_response if specific capture failed (e.g. metadata mismatch)
        final_text = _pick_final_text(
            last_message_content, full_response, *planner_candidates
        )
        parsed_stage = _extract_planning_stage(final_text)
        parsed_itinerary = itinerary_data or await _recover_itinerary_snapshot(
            source_text=final_text,
            history=history,
            user_message=user_message,
            dynamic_context=dynamic_context,
            parsed_stage=parsed_stage,
            is_finalize_turn=is_finalize_turn,
            allow_minimal_fallback=True,
        )

        if is_finalize_turn and not parsed_stage:
            parsed_stage = "complete"

        if parsed_itinerary:
            parsed_itinerary = _normalize_itinerary_for_ui(
                parsed_itinerary,
                destination_hint=_infer_destination_hint(
                    dynamic_context, final_text, user_message
                ),
                context_text="\n".join([dynamic_context, user_message, final_text]),
            )

        if final_text:
            clean_response = _strip_agent_tags(final_text)
            clean_response = re.sub(r"\[STEP:[^\]]*\]", "", clean_response).strip()

            # If the response only contained XML blocks, give it a friendly fallback
            if not clean_response and parsed_itinerary:
                clean_response = "✅ **Itinerary updated!** I have finalized the details and populated your travel plan. You can view the full enriched itinerary in the panel on the right."

            # Ensure we don't save an empty string if everything was stripped
            if not clean_response and not parsed_itinerary:
                clean_response = "I have processed your request. Please let me know if you would like to make any adjustments."

            assistant_msg = ChatMessage(
                chat_room_id=chat_id,
                sender_role=MessageSenderRole.assistant,
                content=clean_response,
                message_metadata={"agent": "langgraph"},
            )
            db.add(assistant_msg)
            await db.flush()

            if parsed_itinerary:
                parsed_itinerary_signature = _itinerary_signature(parsed_itinerary)
                if parsed_itinerary_signature != last_persisted_itinerary_signature:
                    last_persisted_itinerary_signature = await _upsert_itinerary(
                        db,
                        chat_id,
                        parsed_itinerary,
                        source="langgraph_final",
                    )

            if parsed_stage and parsed_stage != last_persisted_stage:
                await _upsert_planning_stage(db, chat_id, parsed_stage)
                last_persisted_stage = parsed_stage

            # Persist assistant output for future KB fallback.
            try:
                from app.agents.rag.vector_store import add_to_knowledge_base

                add_to_knowledge_base(
                    text=(
                        f"Assistant response (langgraph) for chat {chat_id}:\n"
                        f"{clean_response}\n\n"
                        f"Planning stage: {parsed_stage or 'unknown'}"
                    ),
                    metadata={
                        "source": "assistant_response_langgraph",
                        "chat_id": str(chat_id),
                        "stage": parsed_stage or "unknown",
                    },
                )
            except Exception as kb_err:
                logger.warning(
                    "Failed to persist LangGraph response to KB",
                    error=str(kb_err),
                    chat_id=chat_id,
                )

            await db.commit()
            logger.info(
                "LangGraph response saved",
                chat_id=chat_id,
                has_itinerary=parsed_itinerary is not None,
                stage=parsed_stage,
                is_finalize_turn=is_finalize_turn,
            )
    except Exception as e:
        await db.rollback()
        logger.exception("Failed to save final LangGraph output", error=str(e))
