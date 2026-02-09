# Deployment Guide

This repository now includes a fast-path deployment setup for:

- Railway backend hosting (API + worker + Postgres + Redis)
- GitHub Actions CI for backend tests
- GitHub Actions desktop release builds (Electron + bundled renderer + ffmpeg)

## 1) Backend on Railway (fastest path)

Create one Railway project with four services:

1. `api` (from this repo, root dir `backend/`)
2. `worker` (from this repo, root dir `backend/`)
3. `postgres` (Railway Postgres plugin)
4. `redis` (Railway Redis plugin)

### API service config

- Root directory: `backend`
- Build: Dockerfile (`backend/Dockerfile`)
- Start command: use Dockerfile default
- Healthcheck path: `/health/`

The API container runs migrations on boot:

`alembic -c database/alembic.ini upgrade head && uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}`

### Worker service config

- Root directory: `backend`
- Build: Dockerfile (`backend/Dockerfile`)
- Start command override:

`python -m redis_client.worker`

### Core env vars (required)

Set these on both `api` and `worker` unless noted:

- `DATABASE_URL` (api + worker)
- `REDIS_AUTH_URL` (api + worker)
- `REDIS_RQ_URL` (api + worker)
- `GCS_BUCKET` (api + worker)
- `GCS_RENDER_BUCKET` (api + worker)
- `GCP_CREDENTIALS` (api + worker)
- `RENDER_EXECUTION_MODE=local` (api)
- `SESSION_COOKIE_SECURE=true` (api)
- `LOG_LEVEL=INFO` (api + worker)

Use `backend/.env.example` for the full variable list, including optional AI and Cloud Run settings.

## 2) GitHub Actions pipelines

### Backend CI

Workflow: `.github/workflows/backend-ci.yml`

- Trigger: PRs and pushes affecting `backend/**`
- Runs: `python -m pytest tests` from `backend/`

### Backend CD (Railway native autodeploy)

Use Railway's built-in GitHub integration on both `api` and `worker` services:

- Connect each service to this repository and set branch to `main`
- Enable Auto Deploy
- Enable **Wait for CI** so Railway only deploys after `backend-ci` passes

No extra GitHub deploy-hook secrets are required for backend deploys.

### Desktop release build

Workflow: `.github/workflows/desktop-release.yml`

- Trigger: manual (`workflow_dispatch`) or tags matching `desktop-v*`
- Builds Windows installer artifacts
- Bundles:
  - PyInstaller renderer executable
  - ffmpeg and ffprobe binaries

Release artifacts are uploaded to workflow artifacts. Tagged builds also create a GitHub Release.

Required repository secret for release builds:

- `VITE_BACKEND_URL` (example: `https://your-api-domain`)

## 3) Desktop renderer bundle

The desktop build now packages a bundled renderer and ffmpeg tools.

- Bundle script: `desktop/scripts/build_renderer_bundle.py`
- Build script: `npm run build` in `desktop/`
- Electron resources: `desktop/render-bundle`

At runtime, packaged desktop builds now use:

- `resources/render-bundle/renderer(.exe)`
- `resources/render-bundle/ffmpeg(.exe)`
- `resources/render-bundle/ffprobe(.exe)`

Dev mode still falls back to Python entrypoint in `render-job/`.

## 4) Security notes

- Do not put secrets in `VITE_*` values unless you intend to ship them to clients.
- Rotate any previously committed local webhook secrets before production rollout.
- Keep `.env` values in Railway/GitHub secrets, not in git.
