# Agent Guide

This file applies to the repository at `video-editor/`.
Primary code is the FastAPI backend in `backend/`.
The render worker lives in `render-job/`.

## Layout
- `backend/main.py`: FastAPI app entrypoint and router registration.
- `backend/handlers/`: API route definitions (FastAPI routers).
- `backend/operators/`: business logic and DB operations.
- `backend/models/`: Pydantic API models.
- `backend/models/timeline_models.py`: OTIO-inspired timeline schemas.
- `backend/operators/timeline_operator.py`: timeline operations.
- `backend/operators/timeline_editor.py`: timeline editing utilities.
- `backend/database/`: SQLAlchemy base + Alembic migrations.
- `backend/agent/`: background AI asset processing.
- `backend/redis_client/`: Redis/RQ setup and worker.
- `backend/utils/`: external integrations (GCS, embeddings, ffmpeg).
- `backend/tests/`: pytest tests for models and ffmpeg builder.
- `render-job/`: Dockerized render worker for local/GPU rendering.

## Setup
- Work inside `backend/` for Python imports.
- Create a venv: `python -m venv .venv`.
- Activate it, then install deps: `pip install -r requirements.txt`.
- Services needed locally: Postgres + Redis (see docker compose).
- Example: `docker compose -f docker-compose.yaml up -d`.
- Stop services: `docker compose -f docker-compose.yaml down`.

## Run
- API server (from `backend/`): `python main.py`.
- Alternative dev server: `uvicorn main:app --reload`.
- RQ worker (from `backend/`): `python -m redis_client.worker`.
- Migrations: `alembic -c database/alembic.ini upgrade head`.
- New migration: `alembic -c database/alembic.ini revision --autogenerate -m "msg"`.

## Build/Lint/Test
- Build: none; this is a Python service.
- Lint/format: prefer `ruff format` and `ruff check` if available.
- If ruff is not installed, avoid reformatting unless requested.
- Tests live under `backend/tests/` and use pytest.
- Run all tests (from `backend/`): `python -m pytest`.
- Run a test file: `python -m pytest tests/test_ffmpeg_builder.py`.
- Run a single test: `python -m pytest tests/test_ffmpeg_builder.py::test_build_command_string`.

## Render Job (local validation)
- Docker build (CPU): `docker build -t video-render-cpu .\render-job`.
- Docker build (GPU): `docker build -f .\render-job\Dockerfile.gpu -t video-render-gpu .\render-job`.
- The local runner reads manifests via `render-job/entrypoint.py`.
- Test assets live under `backend/test_assets/` and outputs in `backend/test_outputs/`.

## Formatting
- Use 4-space indentation, no tabs.
- Keep line length reasonable (~88-100) and wrap long expressions.
- Prefer explicit, readable code over clever one-liners.
- Keep comments minimal; use them only for non-obvious logic.
- Use module docstrings for large or complex modules.
- Match existing line wrapping and trailing comma usage.
- Prefer f-strings for formatting.

## Imports
- Order imports: standard library, third-party, local.
- Separate groups with blank lines.
- Import only what is used; avoid wildcard imports.
- Prefer absolute imports inside `backend/` (e.g., `from handlers...`).

## Types & Pydantic
- Use Python 3.10+ type hints (`list[str]`, `str | None`).
- Annotate public function inputs/returns.
- Prefer `UUID`/`datetime` types in signatures over raw strings.
- Use Pydantic `BaseModel` for request/response schemas.
- Keep model defaults immutable (avoid `[]` unless intentional).
- Use `datetime` objects; let FastAPI serialize ISO.

## Naming
- `snake_case` for functions, vars, and modules.
- `PascalCase` for classes (Pydantic/SQLAlchemy/dataclasses).
- `UPPER_SNAKE_CASE` for constants/env defaults.
- Use descriptive names for API handlers (`project_create`, etc.).

## FastAPI Handlers
- Define routes in `backend/handlers/` and register in `main.py`.
- Use dependency injection via `Depends`.
- Validate inputs with Pydantic request models.
- Return Pydantic response models with explicit `ok` flags.
- Keep handlers thin; delegate business logic to `operators/`.
- Use `HTTPException` with clear status and detail.

## Operators & Data Access
- Put data access and external calls in `backend/operators/`.
- Accept a SQLAlchemy `Session` from `get_db`.
- Commit explicitly when mutating data.
- Refresh ORM objects after writes when needed.

## Database Models
- Models live in `backend/database/models.py`.
- Use SQLAlchemy ORM patterns consistent with existing models.
- Use `uuid4` defaults for UUID primary keys.
- Store UTC timestamps (`datetime.now(timezone.utc)`).
- Add indexes in `__table_args__` when needed.
- Run Alembic migrations after schema changes.

## Timeline System
- Timeline schemas live in `backend/models/timeline_models.py`.
- Operations are in `backend/operators/timeline_operator.py` and `timeline_editor.py`.
- Keep OTIO-inspired structures consistent (track/clip IDs).
- When adding ops, also update audit logging tables.
- Ensure checkpoints update `Timeline.current_version`.

## Background Jobs
- Enqueue jobs via `rq_queue.enqueue`.
- Keep job payloads serializable (IDs as strings).
- Update status fields (`indexing_status`, timestamps) consistently.
- Re-raise exceptions in workers to allow retries.

## Error Handling & Logging
- Use `HTTPException` in handlers for client-facing errors.
- Use `try/except` around external service calls.
- Record failure state on assets before returning/raising.
- Prefer logging via `logging` over `print` where practical.
- Avoid swallowing exceptions without updating state.

## Environment
- Environment variables are read via `os.getenv` (see code).
- Common vars: `DATABASE_URL`, `REDIS_AUTH_URL`, `REDIS_RQ_URL`.
- Asset storage: `GCS_BUCKET`, `GCP_CREDENTIALS` (JSON string).
- Embeddings: `OPENROUTER_API_KEY` for OpenRouter.
- Use `.env` for local secrets; `.env` is gitignored.

## Repo Hygiene
- Keep changes minimal and aligned with existing patterns.
- Prefer minimal diffs; avoid refactors unrelated to task.
- Do not add new dependencies without updating `backend/requirements.txt`.
- Avoid adding new top-level scripts unless requested.
- Keep AGENTS.md updated when tools or conventions change.

## Cursor/Copilot Rules
- No `.cursor/rules/`, `.cursorrules`, or `.github/copilot-instructions.md` present.
- If any of those files are added later, update this guide to include them.

## Notes
- The backend test suite currently exists and uses pytest.
- `backend/requirements.txt` already includes `pytest` and `pytest-asyncio`.
- If you add tests, mirror module layout under `backend/tests/`.
- Run tests from `backend/` unless a command specifies otherwise.

## Render Job Environment
- The render worker is a separate Docker image under `render-job/`.
- It can run in Cloud Run or locally for validation.
- Local runs use manifest JSONs written next to outputs.
- Keep job payloads and asset maps serializable.
