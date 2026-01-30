import logging
import os
import secrets
from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from database.base import get_db
from database.models import Project
from dependencies.auth import SessionData, get_session
from dependencies.project import require_project
from models.render_models import (
    CancelRenderRequest,
    RenderJobCancelResponse,
    RenderJobCreateResponse,
    RenderJobListResponse,
    RenderJobStatus,
    RenderJobStatusResponse,
    RenderManifestResponse,
    RenderPreset,
    RenderPresetsResponse,
    RenderProgress,
    RenderRequest,
    RenderUploadUrlRequest,
    RenderUploadUrlResponse,
)
from operators.render_operator import (
    MissingAssetsError,
    RenderError,
    RenderValidationError,
    TimelineNotFoundError,
    cancel_render_job,
    create_render_job,
    delete_render_job,
    dispatch_render_job,
    get_render_job,
    list_render_jobs,
    poll_job_status,
    render_job_to_response,
    update_job_status,
)
from utils.gcs_utils import generate_signed_upload_url, generate_signed_url


router = APIRouter(prefix="/projects/{project_id}", tags=["render"])
logger = logging.getLogger(__name__)

GCS_BUCKET = os.getenv("GCS_BUCKET", "video-editor")
GCS_RENDER_BUCKET = os.getenv("GCS_RENDER_BUCKET", "video-editor-renders")
SIGNED_URL_TTL_SECONDS = 3600
WEBHOOK_SECRET = os.getenv("RENDER_WEBHOOK_SECRET")


def verify_render_webhook(
    x_render_webhook_secret: str | None = Header(default=None),
) -> None:
    if not WEBHOOK_SECRET:
        logger.warning("RENDER_WEBHOOK_SECRET not configured; rejecting webhook")
        raise HTTPException(status_code=503, detail="Render webhook not configured")
    if not x_render_webhook_secret or not secrets.compare_digest(
        x_render_webhook_secret, WEBHOOK_SECRET
    ):
        raise HTTPException(status_code=401, detail="Invalid webhook secret")


@router.post("/render", response_model=RenderJobCreateResponse)
async def create_render(
    request: RenderRequest,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_session),
):
    try:
        job = create_render_job(
            db=db,
            project_id=project.project_id,
            request=request,
            created_by=f"user:{session.user_id}",
        )

        job = dispatch_render_job(db, job.job_id)

        return RenderJobCreateResponse(ok=True, job=render_job_to_response(job))

    except TimelineNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="No timeline found for this project. Create a timeline first.",
        )
    except RenderValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except MissingAssetsError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Missing assets required for rendering: {', '.join(e.missing_asset_ids)}",
        )
    except RenderError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/renders", response_model=RenderJobListResponse)
async def list_renders(
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    status: RenderJobStatus | None = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    jobs, total = list_render_jobs(
        db=db,
        project_id=project.project_id,
        status=status,
        limit=limit,
        offset=offset,
    )

    return RenderJobListResponse(
        ok=True,
        jobs=[render_job_to_response(job) for job in jobs],
        total=total,
    )


@router.get("/renders/{job_id}", response_model=RenderJobStatusResponse)
async def get_render_status(
    job_id: UUID,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    poll: bool = Query(False, description="Poll Cloud Run for latest status"),
):
    if poll:
        job = poll_job_status(db, job_id)
    else:
        job = get_render_job(db, job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Render job not found")

    if job.project_id != project.project_id:
        raise HTTPException(status_code=404, detail="Render job not found")

    return RenderJobStatusResponse(ok=True, job=render_job_to_response(job))


@router.get("/renders/{job_id}/manifest", response_model=RenderManifestResponse)
async def get_render_manifest(
    job_id: UUID,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
):
    job = get_render_job(db, job_id)
    if not job or job.project_id != project.project_id:
        raise HTTPException(status_code=404, detail="Render job not found")

    metadata = job.job_metadata or {}
    manifest_path = metadata.get("manifest_path")
    if not manifest_path:
        raise HTTPException(status_code=404, detail="Render manifest not available")

    url = generate_signed_url(
        bucket_name=GCS_BUCKET,
        blob_name=manifest_path,
        expiration=timedelta(seconds=SIGNED_URL_TTL_SECONDS),
    )

    return RenderManifestResponse(
        ok=True,
        manifest_url=url,
        manifest_path=manifest_path,
        expires_in=SIGNED_URL_TTL_SECONDS,
    )


@router.post("/renders/{job_id}/upload-url", response_model=RenderUploadUrlResponse)
async def create_render_upload_url(
    job_id: UUID,
    request: RenderUploadUrlRequest | None = None,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
):
    job = get_render_job(db, job_id)
    if not job or job.project_id != project.project_id:
        raise HTTPException(status_code=404, detail="Render job not found")

    metadata = job.job_metadata or {}
    output_path = metadata.get("output_path")
    if not output_path:
        output_filename = job.output_filename or f"{job.job_id}.mp4"
        output_path = f"{job.project_id}/renders/{output_filename}"

    content_type = None
    if request:
        content_type = request.content_type
    if not content_type:
        content_type = "video/mp4"

    upload_url = generate_signed_upload_url(
        bucket_name=GCS_RENDER_BUCKET,
        blob_name=output_path,
        expiration=timedelta(seconds=SIGNED_URL_TTL_SECONDS),
        content_type=content_type,
    )
    gcs_path = f"gs://{GCS_RENDER_BUCKET}/{output_path}"

    return RenderUploadUrlResponse(
        ok=True,
        upload_url=upload_url,
        gcs_path=gcs_path,
        expires_in=SIGNED_URL_TTL_SECONDS,
    )


@router.post("/renders/{job_id}/cancel", response_model=RenderJobCancelResponse)
async def cancel_render(
    job_id: UUID,
    request: CancelRenderRequest | None = None,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
):
    job = get_render_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Render job not found")

    if job.project_id != project.project_id:
        raise HTTPException(status_code=404, detail="Render job not found")

    try:
        reason = request.reason if request else None
        job = cancel_render_job(db, job_id, reason)
        return RenderJobCancelResponse(ok=True, job=render_job_to_response(job))
    except RenderError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/renders/{job_id}")
async def delete_render(
    job_id: UUID,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
):
    job = get_render_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Render job not found")

    if job.project_id != project.project_id:
        raise HTTPException(status_code=404, detail="Render job not found")

    delete_render_job(db, job_id)

    return {"ok": True}


@router.get("/render/presets", response_model=RenderPresetsResponse)
async def get_presets():
    presets = [
        RenderPreset.draft_preview(),
        RenderPreset.standard_export(),
        RenderPreset.high_quality_export(),
        RenderPreset.maximum_quality_export(),
    ]

    return RenderPresetsResponse(ok=True, presets=presets)


@router.post("/renders/{job_id}/webhook")
async def render_webhook(
    project_id: UUID,
    job_id: UUID,
    progress: RenderProgress,
    db: Session = Depends(get_db),
    _: None = Depends(verify_render_webhook),
):
    if progress.job_id != job_id:
        raise HTTPException(status_code=400, detail="Job ID mismatch")

    job = get_render_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Render job not found")

    if job.project_id != project_id:
        raise HTTPException(status_code=404, detail="Render job not found")

    job = update_job_status(
        db=db,
        job_id=job_id,
        status=progress.status,
        progress=progress.progress,
        current_frame=progress.current_frame,
        error_message=progress.error_message,
        output_url=progress.output_url,
        output_size_bytes=progress.output_size_bytes,
    )

    return {"ok": True, "status": job.status if job else "unknown"}
