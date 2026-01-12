import os
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session as DBSession

from database.models import Assets
from utils.gcs_utils import delete_file, upload_file

ASSET_BUCKET = os.getenv("GCS_ASSET_BUCKET", "video-editor-assets")


def upload_asset(db: DBSession, project_id: UUID, asset_name: str, content: bytes) -> Assets:
    blob_path = f"{project_id}/{asset_name}"
    asset_info = upload_file(
        bucket_name=ASSET_BUCKET,
        contents=content,
        destination_blob_name=blob_path,
    )

    if not asset_info:
        raise Exception("Failed to upload asset to storage")

    asset = Assets(
        asset_name=asset_name,
        asset_url=asset_info["path"],
        asset_type=asset_info.get("content_type", "application/octet-stream"),
        project_id=project_id,
        uploaded_at=datetime.now(timezone.utc),
        asset_summary="",
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
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
