# AGENTS.md
# Video Editor Backend Agent Notes

## Scope
- Applies to the repository at `video_editor/`.
- Primary code is the FastAPI backend under `backend/`.
- Use this file for build/lint/test commands and style guidance.

## Repo Map
- `backend/main.py`: FastAPI app entrypoint and router registration.
- `backend/handlers/`: API route definitions (FastAPI routers).
- `backend/operators/`: business logic and DB operations.
- `backend/models/`: Pydantic API models.
- `backend/database/`: SQLAlchemy base + Alembic migrations.
- `backend/agent/`: background AI asset processing.
- `backend/redis_client/`: Redis/RQ setup and worker.
- `backend/utils/`: external integrations (GCS, embeddings).

## Local Setup
- From repo root, work inside `backend/` for Python imports.
- Create a venv: `python -m venv .venv`.
- Activate it, then install deps: `pip install -r requirements.txt`.
- Services needed locally: Postgres + Redis (see docker compose).
- Example: `docker compose -f docker-compose.yaml up -d`.
- Alembic is used for migrations in `backend/database/`.

## Run Commands
- API server (from `backend/`): `python main.py`.
- Alternative dev server: `uvicorn main:app --reload`.
- RQ worker (from `backend/`): `python -m redis_client.worker`.
- Stop services: `docker compose -f docker-compose.yaml down`.
- Run migrations: `alembic -c database/alembic.ini upgrade head`.
- Create migration: `alembic -c database/alembic.ini revision --autogenerate -m "msg"`.

## Build / Lint / Test
- Build step: none; this is a Python service.
- Install dependencies via `pip install -r requirements.txt`.
- Lint/format tooling is not pinned in the repo.
- A `.ruff_cache/` exists; prefer `ruff format` and `ruff check` if available.
- If ruff is not installed, avoid reformatting unless requested.
- No static type checker configured (no mypy/pyright config).
- No test runner configured or tests present.
- If you add tests, add `pytest` to requirements and document commands.

## Single Test (if pytest is added)
- Run full suite: `python -m pytest`.
- Run file: `python -m pytest path/to/test_file.py`.
- Run single test: `python -m pytest path/to/test_file.py::test_name`.

## Code Style: General
- Keep changes minimal and aligned with existing patterns.
- Use 4-space indentation, no tabs.
- Keep line length reasonable (~88-100) and wrap long expressions.
- Prefer explicit, readable code over clever one-liners.
- Keep comments minimal; prefer self-explanatory code.
- Use module docstrings for large or complex modules.

## Code Style: Imports
- Order imports: standard library, third-party, local.
- Separate groups with blank lines.
- Import only what is used; avoid wildcard imports.
- Prefer absolute imports inside `backend/` (e.g., `from handlers...`).

## Code Style: Types
- Use Python 3.10+ type hints (`list[str]`, `str | None`).
- Annotate public function inputs/returns.
- Prefer `UUID`/`datetime` types in signatures over raw strings.
- Use Pydantic `BaseModel` for request/response schemas.
- Keep model defaults immutable (avoid `[]` unless intentional).

## Code Style: Naming
- `snake_case` for functions, vars, and modules.
- `PascalCase` for classes (Pydantic/SQLAlchemy/dataclasses).
- `UPPER_SNAKE_CASE` for constants/env defaults.
- Use descriptive names for API handlers (`project_create`, etc.).

## API Handlers (FastAPI)
- Define routes in `backend/handlers/` and register in `main.py`.
- Use dependency injection via `Depends`.
- Validate inputs with Pydantic request models.
- Return Pydantic response models with explicit `ok` flags.
- Keep handlers thin; delegate business logic to `operators/`.
- Prefer `HTTPException` with clear status and detail.

## Pydantic Models
- Define request/response schemas in `backend/models/api_models.py`.
- Use explicit field types and defaults.
- Avoid mutable defaults unless intentional; prefer `None` + default factory.
- Keep response models small; map ORM objects in handlers/operators.
- Use `datetime` objects; let FastAPI serialize ISO.

## Operators / Business Logic
- Put data access and external calls in `operators/`.
- Accept a SQLAlchemy `Session` from `get_db`.
- Commit explicitly when mutating data.
- Refresh ORM objects after writes when needed.

## Database / SQLAlchemy
- Models live in `backend/database/models.py`.
- Use SQLAlchemy ORM patterns consistent with existing models.
- Use `uuid4` defaults for UUID primary keys.
- Store UTC timestamps (`datetime.now(timezone.utc)`).
- Add indexes in `__table_args__` when needed.
- Run Alembic migrations after schema changes.

## Timeline / Editing
- Timeline schemas live in `backend/models/timeline_models.py`.
- Operations are in `backend/operators/timeline_operator.py` and `timeline_editor.py`.
- Keep OTIO-inspired structures consistent (track/clip IDs).
- When adding ops, also update audit logging tables.
- Ensure checkpoints update `Timeline.current_version`.

## Background Jobs (RQ)
- Enqueue jobs via `rq_queue.enqueue`.
- Keep job payloads serializable (IDs as strings).
- Update status fields (`indexing_status`, timestamps) consistently.
- Re-raise exceptions in workers to allow retries.

## Error Handling
- Use `HTTPException` in handlers for client-facing errors.
- Use `try/except` around external service calls.
- Record failure state on assets before returning/raising.
- Prefer logging via `logging` over `print` where practical.
- Avoid swallowing exceptions without updating state.

## External Services & Config
- Environment variables are read via `os.getenv` (see code).
- Common vars: `DATABASE_URL`, `REDIS_AUTH_URL`, `REDIS_RQ_URL`.
- Asset storage: `GCS_BUCKET`, `GCP_CREDENTIALS` (JSON string).
- Embeddings: `OPENROUTER_API_KEY` for OpenRouter.
- Use `.env` for local secrets; `.env` is gitignored.

## Formatting Notes
- Keep docstrings in triple quotes.
- Match existing line wrapping and trailing comma usage.
- Prefer f-strings for formatting.

## Testing Notes
- No tests are currently checked in.
- Add tests under a `tests/` package if introducing pytest.
- Mirror module layout when naming tests.

## Cursor / Copilot Rules
- No `.cursor/rules/`, `.cursorrules`, or `.github/copilot-instructions.md` present.

## When Modifying This Repo
- Keep AGENTS.md updated when tools or conventions change.
- Prefer minimal diffs; avoid refactors unrelated to task.
- Do not add new dependencies without updating `backend/requirements.txt`.
- Avoid adding new top-level scripts unless requested.
