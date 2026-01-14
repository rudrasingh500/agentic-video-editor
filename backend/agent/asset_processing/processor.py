"""
Background job processor for asset metadata extraction.

This module provides the main process_asset function that is enqueued
as a background job when assets are uploaded.
"""

import os
from datetime import datetime, timezone

from database.base import get_db
from database.models import Assets
from utils.gcs_utils import download_file

from .analyzers import extract_metadata

ASSET_BUCKET = os.getenv("GCS_BUCKET", "video-editor")


def process_asset(asset_id: str, project_id: str) -> None:
    """
    Background job to extract metadata from an uploaded asset.

    This function is called by the RQ worker to process uploaded assets.
    It downloads the asset from GCS, analyzes it using Gemini 3 Flash,
    and stores the extracted metadata in the database.

    Args:
        asset_id: UUID string of the asset to process
        project_id: UUID string of the project containing the asset

    Raises:
        Exception: Re-raises any exception after updating asset status,
                   allowing RQ to handle retries.
    """
    db = next(get_db())
    asset = None
    try:
        asset = (
            db.query(Assets)
            .filter(Assets.asset_id == asset_id, Assets.project_id == project_id)
            .first()
        )

        if not asset:
            return

        asset.indexing_status = "processing"
        asset.indexing_started_at = datetime.now(timezone.utc)
        asset.indexing_attempts = (asset.indexing_attempts or 0) + 1
        asset.indexing_error = None
        db.commit()

        content = download_file(ASSET_BUCKET, asset.asset_url)
        if not content:
            asset.indexing_status = "failed"
            asset.indexing_error = "Failed to download asset from storage"
            asset.indexing_completed_at = datetime.now(timezone.utc)
            db.commit()
            return

        metadata = extract_metadata(content, asset.asset_type)

        if metadata:
            asset.asset_summary = metadata.get("summary", "")
            asset.asset_tags = metadata.get("tags", [])
            asset.asset_transcript = metadata.get("transcript")
            asset.asset_events = metadata.get("events")
            asset.notable_shots = metadata.get("notable_shots")
            asset.audio_features = metadata.get("audio_features")
            asset.asset_faces = metadata.get("faces")
            asset.asset_objects = metadata.get("objects")
            asset.asset_colors = metadata.get("colors")
            asset.asset_technical = metadata.get("technical")
            asset.asset_scenes = metadata.get("scenes")
            asset.audio_structure = metadata.get("structure")
            asset.asset_speakers = metadata.get("speakers")
            asset.indexing_status = "completed"
            asset.indexing_completed_at = datetime.now(timezone.utc)
            db.commit()
        else:
            asset.indexing_status = "failed"
            asset.indexing_error = f"Unsupported media type: {asset.asset_type}"
            asset.indexing_completed_at = datetime.now(timezone.utc)
            db.commit()

    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        if asset:
            asset.indexing_status = "failed"
            asset.indexing_error = error_msg[:1000]
            asset.indexing_completed_at = datetime.now(timezone.utc)
            db.commit()
        raise
    finally:
        db.close()
