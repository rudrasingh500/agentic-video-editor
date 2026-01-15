from datetime import datetime, timezone
from uuid import UUID
from database.models import Project, VideoOutput
from sqlalchemy.orm import Session as DBSession
from utils.gcs_utils import download_file
import os

ASSET_BUCKET = os.getenv("GCS_BUCKET", "video-editor")


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


def get_video_output(project_id: UUID, db: DBSession) -> bytes:
    video_output = (
        db.query(VideoOutput)
        .filter(VideoOutput.project_id == project_id)
        .order_by(VideoOutput.created_at.desc())
        .first()
    )
    if not video_output:
        raise Exception("No video output found")

    video_bytes = download_file(
        bucket_name=ASSET_BUCKET, blob_name=video_output.video_url
    )
    if not video_bytes:
        raise Exception("Failed to download video")

    return video_bytes
