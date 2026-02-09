# Video Editor Rendering

This repository contains a FastAPI backend (`backend/`) and a render worker image (`render-job/`). The render worker can run in Cloud Run or locally (CPU/GPU) for validation.

## Local render (test assets)

Use the helper script to render the assets in `backend/test_assets` to `backend/test_outputs`:

```powershell
# CPU
 docker build -t video-render-cpu .\render-job
 docker run --rm --entrypoint python `
   -e RENDER_INPUT_DIR=/inputs `
   -e RENDER_OUTPUT_DIR=/outputs `
   -v "C:\Users\rudra\Documents\Granite\video_editor\backend\test_assets:/inputs" `
   -v "C:\Users\rudra\Documents\Granite\video_editor\backend\test_outputs:/outputs" `
   video-render-cpu `
   local_render.py --input-dir /inputs --output-dir /outputs

# GPU (auto backend)
  docker build -f .\render-job\Dockerfile.gpu -t video-render-gpu .\render-job
  docker run --rm --gpus all --entrypoint python `
    -e RENDER_INPUT_DIR=/inputs `
    -e RENDER_OUTPUT_DIR=/outputs `
   -v "C:\Users\rudra\Documents\Granite\video_editor\backend\test_assets:/inputs" `
   -v "C:\Users\rudra\Documents\Granite\video_editor\backend\test_outputs:/outputs" `
    video-render-gpu `
    local_render.py --input-dir /inputs --output-dir /outputs --use-gpu

# GPU (force AMD AMF backend when available)
 docker run --rm --entrypoint python `
   -e RENDER_INPUT_DIR=/inputs `
   -e RENDER_OUTPUT_DIR=/outputs `
   -v "C:\Users\rudra\Documents\Granite\video_editor\backend\test_assets:/inputs" `
   -v "C:\Users\rudra\Documents\Granite\video_editor\backend\test_outputs:/outputs" `
   video-render-cpu `
   local_render.py --input-dir /inputs --output-dir /outputs --use-gpu --gpu-backend amd
```

`local_render.py` writes a manifest JSON next to each output so you can inspect the exact job payload.
When `--use-gpu` is enabled, the renderer now supports NVIDIA NVENC, AMD AMF, and Apple VideoToolbox.
If a requested GPU backend/codec is unavailable in your FFmpeg build, rendering falls back to CPU encoding.

## Backend-configured local rendering (GCS-backed)

The render API accepts execution mode so you can dispatch a job that runs locally while still using GCS for assets and outputs.

### Request payload

```json
{
  "execution_mode": "local",
  "job_type": "export"
}
```

Notes:
- `execution_mode`: `local` or `cloud`.
- Assets and outputs live in GCS; the local runner downloads inputs and uploads outputs automatically.

### Running the manifest locally

Use `render-job/entrypoint.py` and point it at the manifest stored in GCS:

```powershell
$manifest = "gs://video-editor/your-project/manifests/<job-id>.json"
$jobId = "<job-id>"

# Option A: JSON in env var
$creds = Get-Content -Raw "C:\\path\\to\\gcp-creds.json"

docker run --rm --entrypoint python `
  -e GCP_CREDENTIALS="$creds" `
  video-render-cpu `
  entrypoint.py --manifest $manifest --job-id $jobId

# Option B: Mount the service account JSON
$credsPath = "C:\\path\\to\\gcp-creds.json"

docker run --rm --entrypoint python `
  -e GOOGLE_APPLICATION_CREDENTIALS=/secrets/gcp.json `
  -v "$credsPath:/secrets/gcp.json" `
  video-render-cpu `
  entrypoint.py --manifest $manifest --job-id $jobId
```

The entrypoint accepts `gs://...` for Cloud storage manifests.

## Cloud Run rendering

Cloud Run is the default execution mode. The backend uploads the manifest to GCS and dispatches the CPU or GPU job.

## Backend environment defaults

You can set defaults without changing request payloads:

- `RENDER_EXECUTION_MODE`: `cloud` (default) or `local`
