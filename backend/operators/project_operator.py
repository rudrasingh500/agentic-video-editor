import os
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session as DBSession

from database.models import Project, VideoOutput
from utils.gcs_utils import download_file, parse_gcs_url

ASSET_BUCKET = os.getenv("GCS_BUCKET", "video-editor")
RENDER_BUCKET = os.getenv("GCS_RENDER_BUCKET", "video-editor-renders")


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
    return (
        db.query(Project)
        .filter(Project.owner_id == user_id)
        .order_by(Project.updated_at.desc())
        .all()
    )


def list_all_projects(db: DBSession) -> list[Project]:
    return db.query(Project).order_by(Project.updated_at.desc()).all()


def get_video_output(project_id: UUID, db: DBSession) -> bytes:
    video_output = (
        db.query(VideoOutput)
        .filter(VideoOutput.project_id == project_id)
        .order_by(VideoOutput.created_at.desc())
        .first()
    )
    if not video_output:
        raise Exception("No video output found")

    bucket_name = RENDER_BUCKET
    blob_name = video_output.video_url
    parsed = parse_gcs_url(video_output.video_url)
    if parsed:
        bucket_name, blob_name = parsed

    video_bytes = download_file(bucket_name=bucket_name, blob_name=blob_name)
    if not video_bytes and bucket_name != ASSET_BUCKET:
        video_bytes = download_file(bucket_name=ASSET_BUCKET, blob_name=blob_name)

    if not video_bytes:
        raise Exception("Failed to download video")

    return video_bytes


def create_video_output(
    project_id: UUID,
    video_url: str,
    changes: dict[str, Any] | None,
    db: DBSession,
) -> VideoOutput:
    latest = (
        db.query(VideoOutput)
        .filter(VideoOutput.project_id == project_id)
        .order_by(VideoOutput.version.desc())
        .first()
    )
    version = (latest.version + 1) if latest else 1

    output = VideoOutput(
        project_id=project_id,
        video_url=video_url,
        created_at=datetime.now(timezone.utc),
        version=version,
        changes=changes,
    )
    db.add(output)
    db.commit()
    db.refresh(output)
    return output
