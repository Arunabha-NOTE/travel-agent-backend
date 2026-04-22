# LangSmith Agent Evaluation

This folder contains the starter assets to trace and evaluate both backend agents:

- `eval_dataset.jsonl`: 30 travel-planning evaluation cases (LangSmith upload format).
- `eval_dataset.json`: same dataset in array JSON (kept for local tooling/bootstrap).
- `run_langsmith_eval.py`: runs LangGraph and LangChain evaluations against a LangSmith dataset.

## 1) Prerequisites

- Backend dependencies installed.
- Database running and migrated (the runner creates temporary users/chats).
- API keys configured for your LLM/tooling stack.
- LangSmith key available.

## 2) Environment Variables

Set these variables before running the script:

### PowerShell (Windows)

```powershell
$env:LANGCHAIN_TRACING_V2="true"
$env:LANGCHAIN_API_KEY="<your_langsmith_api_key>"
$env:LANGCHAIN_PROJECT="Travel_Agent_Evaluation"
```

Notes:

- `LANGSMITH_API_KEY` is also accepted by the script and mapped to `LANGCHAIN_API_KEY`.
- Keep your existing app variables (LLM, DB, external tools) unchanged.

## 3) Create Dataset in LangSmith

1. Open LangSmith.
2. Go to Datasets & Testing > New Dataset.
3. Choose JSONL and upload `evals/eval_dataset.jsonl`.
4. Name the dataset `Travel_Agent_Eval_Set` (or pass your custom name via `--dataset`).

## 4) Run Evaluations

From `chatbot-backend`:

```powershell
uv run python evals/run_langsmith_eval.py --dataset "Travel_Agent_Eval_Set_30" --max-concurrency 3 --case-timeout-seconds 60
```

The script runs two experiments:

- `LangGraph_Test_*`
- `LangChain_Test_*`

It prints experiment names and comparison URLs when complete.

## 5) What Gets Scored

Two row-level evaluators are included:

- `tool_accuracy`: how many expected tools were called.
- `stage_match`: whether `<planning_stage>` matches the expected stage.

## 6) Troubleshooting

- Missing dataset error: verify the dataset name in LangSmith matches `--dataset`.
- Very long runs: increase `--max-concurrency` and set `--case-timeout-seconds` (for example, 45-90).
- Auth error: verify `LANGCHAIN_API_KEY`/`LANGSMITH_API_KEY`.
- DB/model errors: run migrations first and ensure connection settings are valid.
- Low tool accuracy: inspect each run tree in LangSmith to compare expected vs actual tool calls.
