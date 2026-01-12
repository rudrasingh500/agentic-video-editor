from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from database.base import get_db
from database.models import Project
from dependencies.auth import SessionData, get_session
from dependencies.project import require_project
from models.api_models import (
    ProjectCreateRequest,
    ProjectCreateResponse,
    ProjectDeleteResponse,
    ProjectGetResponse,
    ProjectListResponse,
)
from operators.project_operator import create_project, list_projects, get_video_output


router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("/", response_model=ProjectCreateResponse)
async def project_create(
    request: ProjectCreateRequest,
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_session),
):
    try:
        project = create_project(session.user_id, request.name, db)
    except Exception:
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
        raise HTTPException(status_code=500, detail="Failed to delete project")

    return ProjectDeleteResponse(ok=True)


@router.get("/{project_id}/video")
async def project_video_get(
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
):
    try:
        video_bytes = get_video_output(project.project_id, db)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

    return Response(
        content=video_bytes,
        media_type="video/mp4",
        headers={"Content-Disposition": f"inline; filename={project.project_id}.mp4"},
    )
