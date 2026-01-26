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

## Useful Commands

- Run tests: `pytest`
- Lint/format: `ruff check .`
- Pre-commit hooks: `pre-commit install`
