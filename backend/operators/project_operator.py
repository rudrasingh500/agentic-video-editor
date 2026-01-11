from datetime import datetime, timezone
from uuid import UUID
from database.models import Project, VideoOutput
from sqlalchemy.orm import Session as DBSession


def get_project_by_id(project_id: UUID, db: DBSession) -> Project:
    project = db.query(Project).filter(Project.project_id == project_id).first()
    return project


def create_project(user_id: UUID, name: str, db: DBSession) -> Project:
    project = Project(
        project_name=name,
        owner_id=user_id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def get_project(project_id: UUID, db: DBSession) -> Project:
    project = get_project_by_id(project_id, db)
    return project


def delete_project(project_id: UUID, db: DBSession) -> bool:
    project = get_project_by_id(project_id, db)
    if not project:
        return False
    try:
        db.delete(project)
        db.commit()
        return True
    except Exception:
        return False


def list_projects(user_id: UUID, db: DBSession) -> list[Project]:
    projects = db.query(Project).filter(Project.owner_id == user_id).all()
    return projects


def get_video_output(project_id: UUID, db: DBSession) -> VideoOutput:
    video_output = (
        db.query(VideoOutput)
        .filter(VideoOutput.project_id == project_id)
        .order_by(VideoOutput.created_at.desc())
        .first()
    )
    return video_output
