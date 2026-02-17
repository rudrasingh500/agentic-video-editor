# Granite Video Editor

An AI-native video editor where natural language drives the entire editing workflow. Upload media, describe what you want, and an autonomous agent handles cuts, transitions, captions, color grading, B-roll placement, and rendering -- then verifies its own work by watching the output.

## Architecture

```
desktop/          Electron + React + Tailwind UI
    |
    v  (REST / SSE)
backend/          FastAPI API server
    |--- agent/
    |      |--- edit_agent/      LLM-driven editing orchestrator (Gemini 3 Pro)
    |      |--- asset_processing/ Automated media analysis pipeline
    |--- handlers/               REST endpoints
    |--- operators/              Business logic + DB operations
    |--- models/                 Pydantic schemas (OTIO-inspired timeline)
    |--- database/               SQLAlchemy + Alembic (Postgres + pgvector)
    |--- redis_client/           RQ job queue
    |--- utils/                  GCS, embeddings, FFmpeg, Veo, generation providers
    |
    v  (Cloud Run / Docker)
render-job/       Dockerized FFmpeg render worker (CPU + GPU)
    |--- ffmpeg_renderer.py      Full render pipeline
    |--- graphics_generator.py   Cairo/Pillow overlay compositing
    |--- animation_engine.py     Keyframe animation + easing curves
```

## Key Features

**AI Edit Agent** -- Send a message like *"add captions to the intro and crossfade into the B-roll"* and the agent plans a sequence of timeline operations, executes them against the OTIO-inspired timeline model, renders a preview, watches the result, and self-corrects if something looks wrong. The agent has access to 30+ tools spanning asset search, timeline manipulation, video generation, and quality checks.

**Automated Asset Intelligence** -- Every uploaded asset (video, image, audio) is analyzed by an LLM pipeline that extracts summaries, tags, transcripts with speaker diarization, scene breakdowns, shot types, face/object detection, audio features (BPM, key, structure), and technical metadata. Results are embedded with OpenAI-compatible embeddings and stored in pgvector for semantic search.

**Snippet & Identity System** -- Faces and objects are extracted as snippets with MediaPipe, linked into cross-asset identities via embedding similarity, and organized into character models. The agent can reference identities when generating new content to maintain visual consistency.

**Generative Media** -- Image generation via Gemini 3 Pro and video generation via Google Veo 3.1 are integrated directly into the editing workflow. The agent can generate B-roll, title cards, or replace frames, with an explicit approve/deny gate before anything hits the timeline.

**OTIO-Inspired Timeline** -- The timeline schema mirrors OpenTimelineIO with `RationalTime`, `TimeRange`, `Track`, `Clip`, `Gap`, `Transition`, `Stack`, and `Effect` primitives. Full version history with checkpoint snapshots, operation audit logs, diff comparison, and rollback.

**Render Pipeline** -- Dockerized FFmpeg renderer with support for complex multi-track compositing, 70+ transition types, text/graphic overlays with Cairo, keyframe animations with easing curves, and GPU encoding (NVENC, AMD AMF, VideoToolbox). Runs locally or dispatches to Cloud Run.

**Desktop App** -- Electron app with a timeline panel, waveform display (wavesurfer.js), drag-and-drop media management, asset inspector, people panel for identity management, chat sidebar for AI interaction, render settings, and real-time preview.

## Prerequisites

- Python 3.10+
- Node.js 18+
- Docker (for Postgres, Redis, and render jobs)
- FFmpeg (bundled in render container, or install locally)

## Setup

### Backend

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

Start Postgres and Redis:

```bash
docker compose -f docker-compose.yaml up -d
```

Run database migrations:

```bash
alembic -c database/alembic.ini upgrade head
```

### Desktop

```bash
cd desktop
npm install
```

### Environment Variables

Create a `.env` file in the project root:

```env
DATABASE_URL=postgresql://user:pass@localhost:5432/video_editor
REDIS_AUTH_URL=redis://localhost:6379/0
REDIS_RQ_URL=redis://localhost:6379/1

GCS_BUCKET=your-bucket
GCP_CREDENTIALS={"type": "service_account", ...}

OPENROUTER_API_KEY=sk-or-...
GOOGLE_API_KEY=...                          # For Veo video generation

RENDER_EXECUTION_MODE=local                 # or "cloud"
RENDER_WEBHOOK_SECRET=some-secret

VITE_BACKEND_URL=http://localhost:8000
VITE_DEV_TOKEN=dev-token
VITE_RENDER_WEBHOOK_SECRET=some-secret
```

## Running

### API Server

```bash
cd backend
python main.py
# or
uvicorn main:app --reload
```

### RQ Worker (asset processing + background jobs)

```bash
cd backend
python -m redis_client.worker
```

### Desktop App

```bash
cd desktop
npm run dev
```

### Render Job (local, Docker)

```bash
# CPU
docker build -t video-render-cpu .\render-job
docker run --rm --entrypoint python \
  -v /path/to/inputs:/inputs \
  -v /path/to/outputs:/outputs \
  video-render-cpu \
  local_render.py --input-dir /inputs --output-dir /outputs

# GPU
docker build -f .\render-job\Dockerfile.gpu -t video-render-gpu .\render-job
docker run --rm --gpus all --entrypoint python \
  -v /path/to/inputs:/inputs \
  -v /path/to/outputs:/outputs \
  video-render-gpu \
  local_render.py --input-dir /inputs --output-dir /outputs --use-gpu
```

## Testing

```bash
cd backend
python -m pytest                                          # all tests
python -m pytest tests/test_ffmpeg_builder.py             # single file
python -m pytest tests/test_ffmpeg_builder.py::test_name  # single test
```

## Build

### Desktop Release

```bash
cd desktop
npm run build
```

This compiles TypeScript, bundles with Vite, packages the renderer bundle (FFmpeg + PyInstaller binary), and produces an Electron distributable.

### Render Docker Images

```bash
docker build -t video-render-cpu .\render-job
docker build -f .\render-job\Dockerfile.gpu -t video-render-gpu .\render-job
```

## API Surface

| Group | Prefix | Description |
|-------|--------|-------------|
| Auth | `/auth` | Session creation and validation |
| Projects | `/projects` | CRUD for editing projects |
| Assets | `/projects/{id}/assets` | Upload, list, search media assets |
| Timeline | `/projects/{id}/timeline` | Timeline CRUD, track/clip ops, checkpoints, diff |
| Edit Agent | `/projects/{id}/edit` | Natural language editing (REST + SSE streaming) |
| Render | `/projects/{id}/render` | Render job lifecycle, presets, webhooks |
| Generation | `/projects/{id}/generation` | AI image/video generation requests |
| Snippets | `/projects/{id}/snippets` | Face/object snippet and identity management |
| Health | `/health` | Liveness check |

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API | FastAPI, Pydantic v2, SQLAlchemy, Alembic |
| Database | PostgreSQL, pgvector, Redis |
| AI | Gemini 3 Pro (editing + analysis + image gen), Veo 3.1 (video gen), OpenAI-compatible embeddings |
| Job Queue | Redis Queue (RQ) |
| Render | FFmpeg, Cairo, Pillow, PyInstaller |
| Desktop | Electron, React 18, TypeScript, Tailwind CSS 4, Zustand, wavesurfer.js |
| Storage | Google Cloud Storage |
| Deploy | Railway (backend), Cloud Run (render), Electron Builder (desktop) |

## Third-Party Licenses

This software uses FFmpeg (http://ffmpeg.org), licensed under LGPLv2.1+. FFmpeg is used as an external CLI tool and distributed unmodified. See `render-job/FFMPEG_LICENSE.txt`.
