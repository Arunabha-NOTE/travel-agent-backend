Travel agent chatbot backend powered by FastAPI, LangChain/LangGraph/DeepAgents with RAG and tool integrations for holiday and travel planning.

## Project Setup

1. Clone the repo and enter the backend folder:
   ```bash
   git clone <repo-url>
   cd chatbot-backend
   ```
2. Create a virtual environment (Python >= 3.13):
   ```bash
   python -m venv .venv
   .venv\Scripts\activate  # on Windows
   # source .venv/bin/activate  # on macOS/Linux
   ```
3. Install dependencies for the API (uv recommended since this project is PEP 621/pyproject-native):
   ```bash
   uv venv .venv  # if you want uv to manage the venv (optional)
   uv pip install -e .
   # Optional: install dev tooling (pytest/ruff/pre-commit) if your installer supports groups/extras
   # uv pip install -e ".[dev]"
   ```
4. Configure environment:
   ```bash
   # Windows
   copy .env.example .env
   # macOS/Linux
   cp .env.example .env
   # update secrets, DB, and provider keys
   ```

## Run in Development

Start the FastAPI app with auto-reload using the packaged script from `pyproject.toml`:
```bash
uv run start
```

Alternative (explicit uvicorn invocation):
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open the interactive docs at http://localhost:8000/docs to exercise the endpoints.

## Run with Docker Compose (Backend + Postgres + pgvector)

From the `chatbot-backend` directory:

```bash
docker compose up --build
```

Services:

- API: http://localhost:8000
- Postgres (`pgvector` enabled): `localhost:5432`

The compose stack automatically enables the `vector` extension on first database initialization.

## Authentication (Current)

- Username/password only (no MFA)
- Passwords are hashed with `bcrypt` before storing
- Endpoints:
   - `POST /api/v1/auth/register` with `{ "username": "...", "password": "..." }`
   - `POST /api/v1/auth/login` with `{ "username": "...", "password": "..." }`

## Observability

- **Structured logging**: Request completion logs include `request_id`, `status_code`, `duration_ms`, method, and path.
- **Error wrappers**: Custom exceptions (`AppException` hierarchy) are centrally handled and serialized with consistent error payloads.
- **Prometheus metrics**:
   - `http_requests_total{method,path,status}`
   - `http_request_duration_seconds{path}`
   - `auth_events_total{action,outcome}`
   - `exception_events_total{exception_type,path}`
- **OpenTelemetry traces**:
   - FastAPI auto-instrumentation (incoming HTTP spans)
   - SQLAlchemy and `requests` instrumentation
   - Manual spans for key auth/user operations
   - Exceptions are recorded on active spans

Observability endpoints and config:

- Metrics endpoint: `GET /metrics`
- OTLP target: set `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_TRACES_EXPORTER=otlp`
- Service metadata: `OTEL_SERVICE_NAME`, `ENVIRONMENT`

## Useful Commands

- Run tests: `pytest`
- Lint/format: `ruff check .`
- Pre-commit hooks: `pre-commit install`

## LangSmith Tracing and Agent Evaluation

This backend includes a ready-to-run LangSmith evaluation harness for both agent runtimes.

1. Enable tracing environment variables:
   ```bash
   # PowerShell
   $env:LANGCHAIN_TRACING_V2="true"
   $env:LANGCHAIN_API_KEY="<your_langsmith_api_key>"
   $env:LANGCHAIN_PROJECT="Travel_Agent_Evaluation"
   ```
2. Upload dataset file `evals/eval_dataset.jsonl` in LangSmith as `Travel_Agent_Eval_Set`.
3. Run evaluation script:
   ```bash
   uv run python evals/run_langsmith_eval.py --dataset "Travel_Agent_Eval_Set" --max-concurrency 1
   ```

See `evals/README.md` for full setup notes and troubleshooting.
