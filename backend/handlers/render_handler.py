"""
API handlers for video rendering.

Endpoints:
- POST /projects/{project_id}/render - Start a render job
- GET /projects/{project_id}/renders - List render jobs
- GET /projects/{project_id}/renders/{job_id} - Get render job status
- POST /projects/{project_id}/renders/{job_id}/cancel - Cancel render job
- DELETE /projects/{project_id}/renders/{job_id} - Delete render job
- GET /projects/{project_id}/render/presets - List available presets
- POST /projects/{project_id}/renders/{job_id}/webhook - Status webhook from Cloud Run
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
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
    RenderPreset,
    RenderPresetsResponse,
    RenderProgress,
    RenderRequest,
)
from operators.render_operator import (
    MissingAssetsError,
    RenderError,
    RenderJobNotFoundError,
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


router = APIRouter(prefix="/projects/{project_id}", tags=["render"])


# =============================================================================
# RENDER JOB ENDPOINTS
# =============================================================================


@router.post("/render", response_model=RenderJobCreateResponse)
async def create_render(
    request: RenderRequest,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_session),
):
    """
    Start a new render job.

    Creates a render job for the project's timeline and dispatches it
    to Cloud Run for processing.
    """
    try:
        # Create the job
        job = create_render_job(
            db=db,
            project_id=project.project_id,
            request=request,
            created_by=f"user:{session.user_id}",
        )

        # Dispatch to Cloud Run
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
    """
    List render jobs for a project.

    Returns paginated list of render jobs, optionally filtered by status.
    """
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
    """
    Get render job status.

    If poll=true, will check Cloud Run for the latest status before responding.
    """
    if poll:
        job = poll_job_status(db, job_id)
    else:
        job = get_render_job(db, job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Render job not found")

    if job.project_id != project.project_id:
        raise HTTPException(status_code=404, detail="Render job not found")

    return RenderJobStatusResponse(ok=True, job=render_job_to_response(job))


@router.post("/renders/{job_id}/cancel", response_model=RenderJobCancelResponse)
async def cancel_render(
    job_id: UUID,
    request: CancelRenderRequest | None = None,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
):
    """
    Cancel a render job.

    Only pending or in-progress jobs can be cancelled.
    """
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
    """
    Delete a render job record.

    Note: This does not delete the rendered output from storage.
    """
    job = get_render_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Render job not found")

    if job.project_id != project.project_id:
        raise HTTPException(status_code=404, detail="Render job not found")

    delete_render_job(db, job_id)

    return {"ok": True}


# =============================================================================
# PRESETS ENDPOINT
# =============================================================================


@router.get("/render/presets", response_model=RenderPresetsResponse)
async def get_presets():
    """
    Get available render presets.

    Returns a list of predefined render presets that can be used
    when creating render jobs.
    """
    presets = [
        RenderPreset.draft_preview(),
        RenderPreset.standard_export(),
        RenderPreset.high_quality_export(),
        RenderPreset.maximum_quality_export(),
    ]

    return RenderPresetsResponse(ok=True, presets=presets)


# =============================================================================
# WEBHOOK ENDPOINT (for Cloud Run callbacks)
# =============================================================================


@router.post("/renders/{job_id}/webhook")
async def render_webhook(
    job_id: UUID,
    progress: RenderProgress,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
):
    """
    Webhook endpoint for Cloud Run job status updates.

    Called by the render job container to report progress and completion.
    This endpoint should be protected in production (e.g., with a secret token).
    """
    job = get_render_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Render job not found")

    if job.project_id != project.project_id:
        raise HTTPException(status_code=404, detail="Render job not found")

    # Update job status
    job = update_job_status(
        db=db,
        job_id=job_id,
        status=progress.status,
        progress=progress.progress,
        current_frame=progress.current_frame,
        error_message=progress.error_message,
    )

    return {"ok": True, "status": job.status if job else "unknown"}
