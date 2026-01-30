import os
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from database.base import get_db
from database.models import Project
from dependencies.auth import SessionData, get_session
from dependencies.project import require_project
from models.api_models import (
    OutputShareRequest,
    OutputShareResponse,
    OutputUploadUrlRequest,
    OutputUploadUrlResponse,
    ProjectCreateRequest,
    ProjectCreateResponse,
    ProjectDeleteResponse,
    ProjectGetResponse,
    ProjectListResponse,
)
from operators.project_operator import (
    create_project,
    create_video_output,
    get_video_output,
    list_projects,
)
from utils.gcs_utils import generate_signed_upload_url


router = APIRouter(prefix="/projects", tags=["projects"])
logger = logging.getLogger(__name__)

GCS_RENDER_BUCKET = os.getenv("GCS_RENDER_BUCKET", "video-editor-renders")
SIGNED_URL_TTL_SECONDS = 3600


@router.post("/", response_model=ProjectCreateResponse)
async def project_create(
    request: ProjectCreateRequest,
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_session),
):
    try:
        project = create_project(session.user_id, request.name, db)
    except Exception:
        db.rollback()
        logger.exception("Failed to create project for user %s", session.user_id)
        raise HTTPException(status_code=500, detail="Failed to create project")

    return ProjectCreateResponse(
        ok=True,
        project_id=str(project.project_id),
        project_name=project.project_name,
    )


@router.get("/", response_model=ProjectListResponse)
async def project_list(
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_session),
):
    try:
        projects = list_projects(session.user_id, db)
    except Exception:
        db.rollback()
        logger.exception("Failed to list projects for user %s", session.user_id)
        raise HTTPException(status_code=500, detail="Failed to list projects")

    return ProjectListResponse(
        ok=True,
        projects=[
            {
                "project_id": str(p.project_id),
                "project_name": p.project_name,
                "updated_at": p.updated_at.isoformat(),
            }
            for p in projects
        ],
    )


@router.get("/{project_id}", response_model=ProjectGetResponse)
async def project_get(
    project: Project = Depends(require_project),
):
    return ProjectGetResponse(
        ok=True,
        project_id=str(project.project_id),
        project_name=project.project_name,
    )


@router.delete("/{project_id}", response_model=ProjectDeleteResponse)
async def project_delete(
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
):
    try:
        db.delete(project)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to delete project %s", project.project_id)
        raise HTTPException(status_code=500, detail="Failed to delete project")

    return ProjectDeleteResponse(ok=True)


@router.post("/{project_id}/outputs/upload-url", response_model=OutputUploadUrlResponse)
async def project_output_upload_url(
    request: OutputUploadUrlRequest,
    project: Project = Depends(require_project),
):
    ext = Path(request.filename).suffix
    if not ext:
        ext = ".mp4"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_filename = f"desktop_{timestamp}_{uuid4().hex}{ext}"
    blob_path = f"{project.project_id}/outputs/{output_filename}"

    content_type = request.content_type or "video/mp4"
    upload_url = generate_signed_upload_url(
        bucket_name=GCS_RENDER_BUCKET,
        blob_name=blob_path,
        expiration=timedelta(seconds=SIGNED_URL_TTL_SECONDS),
        content_type=content_type,
    )
    gcs_path = f"gs://{GCS_RENDER_BUCKET}/{blob_path}"

    return OutputUploadUrlResponse(
        ok=True,
        upload_url=upload_url,
        gcs_path=gcs_path,
        expires_in=SIGNED_URL_TTL_SECONDS,
    )


@router.post("/{project_id}/outputs", response_model=OutputShareResponse)
async def project_output_share(
    request: OutputShareRequest,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
):
    output = create_video_output(
        project_id=project.project_id,
        video_url=request.gcs_path,
        changes=request.changes,
        db=db,
    )

    return OutputShareResponse(
        ok=True,
        video_id=str(output.video_id),
        video_url=output.video_url,
        version=output.version,
        created_at=output.created_at,
    )


@router.get("/{project_id}/video")
async def project_video_get(
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
):
    try:
        video_bytes = get_video_output(project.project_id, db)
    except Exception as e:
        logger.exception("Failed to fetch video output for project %s", project.project_id)
        raise HTTPException(status_code=404, detail=str(e))

    return Response(
        content=video_bytes,
        media_type="video/mp4",
        headers={"Content-Disposition": f"inline; filename={project.project_id}.mp4"},
    )
