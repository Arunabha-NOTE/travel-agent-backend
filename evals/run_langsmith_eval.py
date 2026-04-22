"""Run LangSmith evaluation for LangChain and LangGraph travel agents."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langsmith import Client
from langsmith.evaluation import aevaluate
from langsmith.utils import LangSmithNotFoundError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.langchain_agent import run_langchain_agent
from app.agents.langgraph_agent import run_langgraph_agent
from app.db.session import async_session_maker
from app.models.chat_message import ChatMessage, MessageSenderRole
from app.models.chat_room import ChatRoom
from app.models.planning_session import PlanningSession
from app.models.user import User

STAGE_PATTERN = re.compile(
    r"<planning_stage>\s*([a-z_]+)\s*</planning_stage>", re.IGNORECASE
)


def _extract_stage(text: str) -> str:
    matches = STAGE_PATTERN.findall(text or "")
    if not matches:
        return "unknown"
    return matches[-1].strip().lower()


def _copy_history(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(item) for item in history]


async def _create_eval_chat(db: AsyncSession) -> uuid.UUID:
    user = User(
        username=f"ls_eval_{uuid.uuid4().hex[:12]}",
        hashed_password="langsmith-eval-placeholder",
        is_active=True,
    )
    db.add(user)
    await db.flush()

    chat = ChatRoom(user_id=user.id, title="LangSmith Evaluation Chat")
    db.add(chat)
    await db.flush()
    await db.commit()
    return chat.id


async def _run_streaming_agent(
    *,
    runner: Callable[..., Any],
    inputs: dict[str, Any],
    case_timeout_seconds: int,
) -> dict[str, Any]:
    chat_history = _copy_history(inputs.get("chat_history", []))
    user_query = str(inputs.get("user_query", "")).strip()

    if not user_query:
        return {
            "output": "",
            "final_stage": "unknown",
            "error": "Missing user_query in dataset inputs.",
        }

    async with async_session_maker() as db:
        chat_id = await _create_eval_chat(db)
        chunks: list[str] = []

        async def _collect_stream() -> list[str]:
            streamed: list[str] = []
            async for token in runner(
                chat_id=chat_id,
                user_message=user_query,
                history=chat_history,
                db=db,
            ):
                streamed.append(token)
            return streamed

        timed_out = False
        error_text = ""

        try:
            chunks = await asyncio.wait_for(
                _collect_stream(), timeout=case_timeout_seconds
            )
        except TimeoutError:
            timed_out = True
            error_text = f"Timed out after {case_timeout_seconds}s"
        except Exception as exc:
            error_text = str(exc)

        stream_text = "".join(chunks).strip()

        planning_stage = "unknown"
        planning_result = await db.execute(
            select(PlanningSession.stage).where(PlanningSession.chat_room_id == chat_id)
        )
        persisted_stage = planning_result.scalar_one_or_none()
        if persisted_stage:
            planning_stage = str(persisted_stage).lower()

        assistant_result = await db.execute(
            select(ChatMessage.content)
            .where(
                ChatMessage.chat_room_id == chat_id,
                ChatMessage.sender_role == MessageSenderRole.assistant,
            )
            .order_by(ChatMessage.created_at.desc())
            .limit(1)
        )
        assistant_text = assistant_result.scalar_one_or_none() or ""

        best_text = assistant_text.strip() or stream_text
        final_stage = _extract_stage(best_text)
        if final_stage == "unknown" and planning_stage != "unknown":
            final_stage = planning_stage

        payload: dict[str, Any] = {
            "output": best_text,
            "final_stage": final_stage,
            "timed_out": timed_out,
        }
        if error_text:
            payload["error"] = error_text
        return payload


def _walk_tool_calls(run: Any) -> list[str]:
    names: list[str] = []
    stack = [run]

    while stack:
        current = stack.pop()
        child_runs = list(getattr(current, "child_runs", []) or [])
        stack.extend(child_runs)
        for child in child_runs:
            if getattr(child, "run_type", "") == "tool":
                tool_name = getattr(child, "name", "")
                if tool_name:
                    names.append(tool_name)

    return names


def tool_calling_evaluator(run: Any, example: Any) -> dict[str, Any]:
    expected = list(
        (getattr(example, "outputs", {}) or {}).get("expected_tools_called", [])
    )
    called = _walk_tool_calls(run)

    if not expected:
        score = 1.0
        matched = []
    else:
        matched = [tool for tool in expected if tool in called]
        score = len(matched) / len(expected)

    return {
        "key": "tool_accuracy",
        "score": score,
        "comment": (
            f"expected={expected}; matched={matched}; called={called}"
            if expected
            else f"expected no required tools; called={called}"
        ),
    }


def stage_evaluator(run: Any, example: Any) -> dict[str, Any]:
    outputs = getattr(run, "outputs", {}) or {}
    predicted_stage = str(outputs.get("final_stage") or "unknown").lower()
    expected_stage = str(
        (getattr(example, "outputs", {}) or {}).get("expected_final_stage", "unknown")
    ).lower()

    return {
        "key": "stage_match",
        "score": 1.0 if predicted_stage == expected_stage else 0.0,
        "comment": f"expected={expected_stage}; predicted={predicted_stage}",
    }


async def run_langchain_case(inputs: dict[str, Any]) -> dict[str, Any]:
    timeout_seconds = int(inputs.get("case_timeout_seconds", 180))
    return await _run_streaming_agent(
        runner=run_langchain_agent,
        inputs=inputs,
        case_timeout_seconds=timeout_seconds,
    )


async def run_langgraph_case(inputs: dict[str, Any]) -> dict[str, Any]:
    timeout_seconds = int(inputs.get("case_timeout_seconds", 180))
    return await _run_streaming_agent(
        runner=run_langgraph_agent,
        inputs=inputs,
        case_timeout_seconds=timeout_seconds,
    )


def _ensure_langsmith_env(project: str) -> None:
    if os.getenv("LANGSMITH_API_KEY") and not os.getenv("LANGCHAIN_API_KEY"):
        os.environ["LANGCHAIN_API_KEY"] = os.environ["LANGSMITH_API_KEY"]

    if not os.getenv("LANGCHAIN_API_KEY"):
        raise RuntimeError(
            "Set LANGCHAIN_API_KEY (or LANGSMITH_API_KEY) before running evaluation."
        )

    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGCHAIN_PROJECT", project)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate LangChain and LangGraph travel agents on a LangSmith dataset."
    )
    parser.add_argument(
        "--dataset",
        default="Travel_Agent_Eval_Set",
        help="LangSmith dataset name.",
    )
    parser.add_argument(
        "--project",
        default="Travel_Agent_Evaluation",
        help="LangSmith project name used for traces and experiments.",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=1,
        help="Concurrent dataset examples per evaluation run.",
    )
    parser.add_argument(
        "--case-timeout-seconds",
        type=int,
        default=180,
        help="Timeout per dataset case in seconds.",
    )
    return parser.parse_args()


def _load_examples_from_local_dataset() -> list[dict[str, Any]]:
    eval_dir = Path(__file__).resolve().parent
    jsonl_file = eval_dir / "eval_dataset.jsonl"
    json_file = eval_dir / "eval_dataset.json"

    rows: list[dict[str, Any]] = []
    if jsonl_file.exists():
        with jsonl_file.open("r", encoding="utf-8") as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped:
                    continue
                parsed = json.loads(stripped)
                if isinstance(parsed, dict):
                    rows.append(parsed)
    elif json_file.exists():
        with json_file.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        if not isinstance(payload, list):
            raise RuntimeError("eval_dataset.json must contain a top-level JSON array.")
        rows = [row for row in payload if isinstance(row, dict)]
    else:
        raise RuntimeError(
            "No local dataset found. Expected eval_dataset.jsonl or eval_dataset.json."
        )

    examples: list[dict[str, Any]] = []
    for row in rows:
        examples.append(
            {
                "inputs": row.get("inputs", {}),
                "outputs": row.get("outputs", {}),
                "metadata": {
                    "test_type": row.get("test_type", "unknown"),
                },
            }
        )

    if not examples:
        raise RuntimeError("No valid examples found in local eval dataset file.")

    return examples


def _ensure_dataset_exists(client: Client, dataset_name: str) -> None:
    try:
        client.read_dataset(dataset_name=dataset_name)
        return
    except LangSmithNotFoundError:
        pass

    examples = _load_examples_from_local_dataset()
    print(
        f"Dataset '{dataset_name}' not found. Creating from local eval dataset file..."
    )
    client.create_dataset(
        dataset_name=dataset_name,
        description="Travel agent evaluation set bootstrapped from local eval dataset file",
    )
    client.create_examples(dataset_name=dataset_name, examples=examples)
    print(f"Created dataset '{dataset_name}' with {len(examples)} examples.")


async def _main_async() -> None:
    load_dotenv()

    args = _parse_args()
    _ensure_langsmith_env(args.project)

    client = Client()
    _ensure_dataset_exists(client, args.dataset)
    evaluators = [tool_calling_evaluator, stage_evaluator]

    async def _run_langgraph_with_timeout(inputs: dict[str, Any]) -> dict[str, Any]:
        payload = dict(inputs)
        payload["case_timeout_seconds"] = args.case_timeout_seconds
        return await run_langgraph_case(payload)

    async def _run_langchain_with_timeout(inputs: dict[str, Any]) -> dict[str, Any]:
        payload = dict(inputs)
        payload["case_timeout_seconds"] = args.case_timeout_seconds
        return await run_langchain_case(payload)

    print(f"Running LangGraph evaluation on dataset: {args.dataset}")
    langgraph_results = await aevaluate(
        _run_langgraph_with_timeout,
        data=args.dataset,
        evaluators=evaluators,
        experiment_prefix="LangGraph_Test_",
        client=client,
        max_concurrency=args.max_concurrency,
        metadata={"agent_runtime": "langgraph"},
        error_handling="log",
    )
    print(f"LangGraph experiment: {langgraph_results.experiment_name}")
    if langgraph_results.url:
        print(f"LangGraph results URL: {langgraph_results.url}")

    print(f"Running LangChain evaluation on dataset: {args.dataset}")
    langchain_results = await aevaluate(
        _run_langchain_with_timeout,
        data=args.dataset,
        evaluators=evaluators,
        experiment_prefix="LangChain_Test_",
        client=client,
        max_concurrency=args.max_concurrency,
        metadata={"agent_runtime": "langchain"},
        error_handling="log",
    )
    print(f"LangChain experiment: {langchain_results.experiment_name}")
    if langchain_results.url:
        print(f"LangChain results URL: {langchain_results.url}")


def main() -> None:
    try:
        asyncio.run(_main_async())
    except KeyboardInterrupt:
        print("Evaluation cancelled by user.")


if __name__ == "__main__":
    main()
