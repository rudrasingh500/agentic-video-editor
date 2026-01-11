from uuid import UUID
from fastapi import Depends, HTTPException, Path
from sqlalchemy.orm import Session

from database.base import get_db
from database.models import Project
from dependencies.auth import get_session, SessionData


def require_project(
    project_id: UUID = Path(...),
    session: SessionData = Depends(get_session),
    db: Session = Depends(get_db),
) -> Project:
    project = (
        db.query(Project)
        .filter(
            Project.project_id == project_id,
            Project.owner_id == session.user_id,
        )
        .first()
    )

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return project
