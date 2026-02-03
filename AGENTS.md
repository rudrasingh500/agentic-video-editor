# Agent Guide

This file applies to the repository at `video_editor/`.
Primary code is the FastAPI backend in `backend/`.
Desktop UI lives in `desktop/` and the render worker in `render-job/`.

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
- `desktop/src/`: React + Tailwind UI.
- `desktop/src/lib/`: API client, config, and shared types.
- `desktop/src/screens/`: top-level screens.
- `desktop/src/components/`: shared UI components.
- `render-job/`: Dockerized render worker for local/GPU rendering.
- `render-job/entrypoint.py`: render job entrypoint.
- `render-job/local_render.py`: local render helper.

## Setup
- Work inside `backend/` for Python imports.
- Create a venv: `python -m venv .venv`.
- Activate it, then install deps: `pip install -r requirements.txt`.
- Services needed locally: Postgres + Redis (see `backend/docker-compose.yaml`).
- Start services: `docker compose -f backend/docker-compose.yaml up -d`.
- Stop services: `docker compose -f backend/docker-compose.yaml down`.
- Desktop deps: `npm install` in `desktop/`.

## Run
- API server (from `backend/`): `python main.py`.
- Alternative dev server: `uvicorn main:app --reload`.
- RQ worker (from `backend/`): `python -m redis_client.worker`.
- Migrations: `alembic -c database/alembic.ini upgrade head`.
- New migration: `alembic -c database/alembic.ini revision --autogenerate -m "msg"`.
- Desktop dev: `npm run dev` (from `desktop/`).
- Local render helper: `python local_render.py --input-dir <dir> --output-dir <dir>` (from `render-job/`).

## Build/Lint/Test
- Build: none; the backend is a Python service.
- Lint/format: prefer `ruff format` and `ruff check` if available.
- Tests live under `backend/tests/` and use pytest.
- Run all tests (from `backend/`): `python -m pytest`.
- Run a test file: `python -m pytest tests/test_ffmpeg_builder.py`.
- Run a single test: `python -m pytest tests/test_ffmpeg_builder.py::test_build_command_string`.
- Desktop build: `npm run build` (runs `tsc`, `vite build`, `electron-builder`).
- Desktop lint: `npm run lint` (no frontend tests configured).
- Render job Docker (CPU): `docker build -t video-render-cpu .\render-job`.
- Render job Docker (GPU): `docker build -f .\render-job\Dockerfile.gpu -t video-render-gpu .\render-job`.
- Test assets live under `backend/test_assets/` and outputs in `backend/test_outputs/`.

## Formatting
- Use 4-space indentation, no tabs.
- Keep line length reasonable (~88-100) and wrap long expressions.
- Keep comments minimal; use docstrings for complex modules.
- Prefer f-strings for formatting.

## Imports
- Order imports: standard library, third-party, local.
- Separate groups with blank lines; import only what is used; avoid wildcard imports.
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
- Define routes in `backend/handlers/` and register in `backend/main.py`.
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

## Frontend (desktop)
- Use TypeScript in `desktop/src/` with function components and hooks.
- Keep API calls in `desktop/src/lib/api.ts`; update DTOs in `desktop/src/lib/types.ts`.
- Prefer `import type` for type-only imports.
- Use Tailwind utilities; base styles live in `desktop/src/index.css`.
- Config/env values come from `desktop/src/lib/config.ts` (`VITE_*`).

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
- Desktop env: `VITE_BACKEND_URL`, `VITE_DEV_TOKEN`, `VITE_RENDER_WEBHOOK_SECRET`.
- Use `.env` for local secrets; `.env` is gitignored.

## Repo Hygiene
- Keep changes minimal and aligned with existing patterns.
- Prefer minimal diffs; avoid refactors unrelated to task.
- Do not add new Python deps without updating `backend/requirements.txt`.
- Do not add new JS deps without updating `desktop/package.json`.
- Avoid adding new top-level scripts unless requested.
- Keep AGENTS.md updated when tools or conventions change.
- Do not commit `.env` or other secrets.

## Cursor/Copilot Rules
- No `.cursor/rules/`, `.cursorrules`, or `.github/copilot-instructions.md` present.
- If any of those files are added later, update this guide to include them.
