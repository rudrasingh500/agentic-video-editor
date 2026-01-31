import os
import mimetypes
from datetime import datetime, timezone
from uuid import UUID

from rq import Retry
from sqlalchemy.orm import Session as DBSession

from agent.asset_processing import process_asset
from database.models import Assets
from redis_client import rq_queue
from utils.gcs_utils import delete_file, upload_file

ASSET_BUCKET = os.getenv("GCS_BUCKET", "video-editor")


def _resolve_content_type(
    asset_name: str, content_type: str | None
) -> str:
    if content_type and content_type != "application/octet-stream":
        return content_type
    guessed, _ = mimetypes.guess_type(asset_name)
    return guessed or content_type or "application/octet-stream"


def upload_asset(
    db: DBSession,
    project_id: UUID,
    asset_name: str,
    content: bytes,
    content_type: str | None = None,
) -> Assets:
    blob_path = f"{project_id}/{asset_name}"
    resolved_type = _resolve_content_type(asset_name, content_type)
    asset_info = upload_file(
        bucket_name=ASSET_BUCKET,
        contents=content,
        destination_blob_name=blob_path,
        content_type=resolved_type,
    )

    if not asset_info:
        raise Exception("Failed to upload asset to storage")

    asset = Assets(
        asset_name=asset_name,
        asset_url=asset_info["path"],
        asset_type=asset_info.get("content_type") or resolved_type,
        project_id=project_id,
        uploaded_at=datetime.now(timezone.utc),
        asset_summary="",
        indexing_status="pending",
        indexing_attempts=0,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)

    rq_queue.enqueue(
        process_asset,
        str(asset.asset_id),
        str(project_id),
        job_timeout=600,
        retry=Retry(max=3, interval=[10, 30, 60]),
    )

    return asset


def delete_asset(db: DBSession, project_id: UUID, asset_id: UUID) -> bool:
    asset = (
        db.query(Assets)
        .filter(Assets.project_id == project_id, Assets.asset_id == asset_id)
        .first()
    )

    if not asset:
        return False

    delete_file(bucket_name=ASSET_BUCKET, blob_name=asset.asset_url)

    db.delete(asset)
    db.commit()
    return True


def list_assets(db: DBSession, project_id: UUID) -> list[Assets]:
    return db.query(Assets).filter(Assets.project_id == project_id).all()


def get_asset(db: DBSession, project_id: UUID, asset_id: UUID) -> Assets | None:
    return (
        db.query(Assets)
        .filter(Assets.project_id == project_id, Assets.asset_id == asset_id)
        .first()
    )


def reindex_asset(db: DBSession, project_id: UUID, asset_id: UUID) -> Assets | None:
    asset = (
        db.query(Assets)
        .filter(Assets.project_id == project_id, Assets.asset_id == asset_id)
        .first()
    )

    if not asset:
        return None

    asset.indexing_status = "pending"
    asset.indexing_error = None
    db.commit()

    rq_queue.enqueue(
        process_asset,
        str(asset_id),
        str(project_id),
        job_timeout=600,
        retry=Retry(max=3, interval=[10, 30, 60]),
    )

    db.refresh(asset)
    return asset
