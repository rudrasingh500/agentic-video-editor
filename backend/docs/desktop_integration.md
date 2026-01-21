# Desktop Integration Guide

This guide explains how a desktop app can work with the remote backend while
rendering locally. GCS is the default storage for shared assets and optional
shared outputs.

## Overview
- The backend stays remote (FastAPI).
- The desktop app renders locally using the render manifest schema.
- GCS is the source of truth for shared assets and shared outputs.
- Local renders are offline by default and only touch the backend when you
  explicitly share outputs or when the agent creates render jobs.
- Default render execution mode is local. Set `RENDER_EXECUTION_MODE=cloud`
  only if you want to enable Cloud Run dispatch.

## Temporary Auth (Dev Token)
For desktop prototyping, use a fixed bearer token.

Set environment variable:

```
DEV_API_TOKEN=your-dev-token
```

Send the token with every request:

```
Authorization: Bearer your-dev-token
```

This is intentionally minimal and will be replaced by Stych later.

## Asset Flow
### Upload
```
POST /projects/{project_id}/assets
Content-Type: multipart/form-data
```

### List
```
GET /projects/{project_id}/assets
```

### Download (Signed URL)
```
GET /projects/{project_id}/assets/{asset_id}/download
```

Response:
```
{
  "ok": true,
  "url": "https://storage.googleapis.com/...",
  "expires_in": 3600
}
```

### Local Asset Override
The manifest uses GCS paths by default. The desktop app should keep a local
cache keyed by `asset_id`. When rendering, replace any `asset_map[asset_id]`
entry with an absolute local path if the file exists locally.

## Offline Local Render (Default)
No backend calls are required for a local-only render.

1. Build a render manifest locally using the same schema as
   `RenderManifest` in `backend/models/render_models.py`.
2. For any asset that exists locally, replace its GCS path in `asset_map`
   with the absolute local file path.
3. Render locally and keep the output local.

## Agent-Tracked Render (Backend Job)
When the agent triggers a render, the backend owns the job record.

### Create Job
```
POST /projects/{project_id}/render
```

### Fetch Manifest
```
GET /projects/{project_id}/renders/{job_id}/manifest
```

Response:
```
{
  "ok": true,
  "manifest_url": "https://storage.googleapis.com/...",
  "manifest_path": "{project_id}/manifests/{job_id}.json",
  "expires_in": 3600
}
```

### Render Locally
- Download the manifest.
- Rewrite `asset_map` entries to absolute local paths when available.
- Render locally.

### Upload Output (Signed URL)
```
POST /projects/{project_id}/renders/{job_id}/upload-url
```

Response:
```
{
  "ok": true,
  "upload_url": "https://storage.googleapis.com/...",
  "gcs_path": "gs://bucket/project_id/renders/output.mp4",
  "expires_in": 3600
}
```

Upload the file using the signed URL (HTTP PUT), then notify the backend:

```
POST /projects/{project_id}/renders/{job_id}/webhook
```

Payload example:
```
{
  "job_id": "...",
  "status": "completed",
  "progress": 100,
  "output_url": "gs://bucket/project_id/renders/output.mp4",
  "output_size_bytes": 12345678
}
```

### Poll Status (Optional)
```
GET /projects/{project_id}/renders/{job_id}
```

## Optional Share (Local Render -> Project)
If the user wants to share a local render, use these endpoints.

### Get Upload URL
```
POST /projects/{project_id}/outputs/upload-url
```

Body example:
```
{
  "filename": "final.mp4",
  "content_type": "video/mp4"
}
```

Response:
```
{
  "ok": true,
  "upload_url": "https://storage.googleapis.com/...",
  "gcs_path": "gs://bucket/project_id/outputs/desktop_...mp4",
  "expires_in": 3600
}
```

Upload the file using the signed URL (HTTP PUT).

### Register Output
```
POST /projects/{project_id}/outputs
```

Body example:
```
{
  "gcs_path": "gs://bucket/project_id/outputs/desktop_...mp4",
  "changes": {
    "note": "Local render share"
  }
}
```

Response:
```
{
  "ok": true,
  "video_id": "...",
  "video_url": "gs://bucket/project_id/outputs/desktop_...mp4",
  "version": 1,
  "created_at": "2026-01-21T00:00:00Z"
}
```

## Notes
- Signed URLs expire after one hour.
- If you can render from local files, update the manifest locally and avoid
  any asset downloads.
- Agent-tracked renders should always report status to the backend.
