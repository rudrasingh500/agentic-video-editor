import os
import logging
import mimetypes
from datetime import datetime, timedelta, timezone

from database.base import get_db
from database.models import Assets
from utils.gcs_utils import download_file, generate_signed_url
from utils.embeddings import get_embedding, build_embedding_text
from operators.snippet_operator import create_snippet

from .analyzers import extract_metadata
from .entity_linker import link_asset_entities
from .snippet_extractor import extract_snippets_from_asset
from .snippet_linker import strict_auto_link_snippet

ASSET_BUCKET = os.getenv("GCS_BUCKET", "video-editor")
logger = logging.getLogger(__name__)


def process_asset(asset_id: str, project_id: str) -> None:
    db = next(get_db())
    asset = None
    try:
        asset = (
            db.query(Assets)
            .filter(Assets.asset_id == asset_id, Assets.project_id == project_id)
            .first()
        )

        if not asset:
            logger.warning(
                "Asset %s not found for project %s during indexing",
                asset_id,
                project_id,
            )
            return

        logger.info("Indexing asset %s for project %s", asset_id, project_id)
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
            logger.error(
                "Failed to download asset %s for project %s",
                asset_id,
                project_id,
            )
            return

        content_type = asset.asset_type
        if not content_type or content_type == "application/octet-stream":
            guessed, _ = mimetypes.guess_type(asset.asset_name)
            if guessed:
                content_type = guessed
                asset.asset_type = guessed

        metadata_source_url = None
        try:
            metadata_source_url = generate_signed_url(
                bucket_name=ASSET_BUCKET,
                blob_name=asset.asset_url,
                expiration=timedelta(hours=2),
            )
        except Exception as signed_url_error:
            logger.warning(
                "Failed to create signed URL for metadata analysis on asset %s: %s",
                asset_id,
                str(signed_url_error),
            )

        metadata = extract_metadata(
            content,
            content_type,
            source_url=metadata_source_url,
        )

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

            embedding_text = build_embedding_text(
                summary=asset.asset_summary,
                tags=asset.asset_tags,
            )
            embedding = get_embedding(embedding_text)
            if embedding:
                asset.embedding = embedding

            asset.indexing_status = "completed"
            asset.indexing_completed_at = datetime.now(timezone.utc)
            db.commit()
            logger.info("Completed indexing asset %s", asset_id)

            # Link entities and compute cross-asset similarities
            try:
                link_result = link_asset_entities(asset, db)
                logger.info(
                    "Entity linking for asset %s: %d entities, %d potential matches",
                    asset_id,
                    link_result.get("entities_created", 0),
                    link_result.get("similarities_found", 0),
                )
            except Exception as e:
                logger.warning(
                    "Entity linking failed for asset %s: %s (non-fatal)",
                    asset_id,
                    str(e),
                )

            # Extract snippets (face/person) and auto-link identities
            try:
                extracted_snippets = extract_snippets_from_asset(content, content_type)
                snippet_results = {
                    "created": 0,
                    "auto_attached": 0,
                    "suggested": 0,
                    "new_identity": 0,
                    "skipped": 0,
                    "failed": 0,
                }
                for item in extracted_snippets:
                    snippet_type = item.get("snippet_type", "face")
                    try:
                        with db.begin_nested():
                            snippet_source_type = (
                                "generated_asset"
                                if str(asset.asset_type).startswith("image/")
                                else "video_ingest"
                            )
                            snippet = create_snippet(
                                db=db,
                                project_id=asset.project_id,
                                asset_id=asset.asset_id,
                                snippet_type=snippet_type,
                                source_type=snippet_source_type,
                                source_ref={
                                    "asset_id": str(asset.asset_id),
                                    "asset_name": asset.asset_name,
                                    "asset_type": asset.asset_type,
                                },
                                frame_index=item.get("frame_index"),
                                timestamp_ms=item.get("timestamp_ms"),
                                bbox=item.get("bbox"),
                                descriptor=item.get("descriptor"),
                                embedding=item.get("embedding"),
                                tags=item.get("tags") or [],
                                quality_score=item.get("quality_score"),
                                crop_bytes=item.get("crop_bytes"),
                                preview_bytes=item.get("preview_bytes"),
                                created_by="system:asset_processor",
                            )
                            snippet_results["created"] += 1

                            if snippet.snippet_type not in {"face", "item"}:
                                snippet_results["skipped"] += 1
                                continue

                            decision = strict_auto_link_snippet(db, snippet)
                            key = decision.get("decision")
                            if key in snippet_results:
                                snippet_results[key] += 1
                    except Exception as snippet_error:
                        snippet_results["failed"] += 1
                        logger.warning(
                            (
                                "Snippet create/link failed for asset %s "
                                "frame=%s type=%s: %s"
                            ),
                            asset_id,
                            item.get("frame_index"),
                            snippet_type,
                            str(snippet_error),
                        )

                db.commit()
                logger.info(
                    "Snippet extraction for asset %s: %s",
                    asset_id,
                    snippet_results,
                )
            except Exception as e:
                db.rollback()
                logger.warning(
                    "Snippet extraction/linking failed for asset %s: %s (non-fatal)",
                    asset_id,
                    str(e),
                )
        else:
            asset.indexing_status = "failed"
            asset.indexing_error = f"Unsupported media type: {asset.asset_type}"
            asset.indexing_completed_at = datetime.now(timezone.utc)
            db.commit()
            logger.error(
                "Unsupported media type %s for asset %s",
                asset.asset_type,
                asset_id,
            )

    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        if asset:
            asset.indexing_status = "failed"
            asset.indexing_error = error_msg[:1000]
            asset.indexing_completed_at = datetime.now(timezone.utc)
            db.commit()
        logger.exception("Asset indexing failed for asset %s", asset_id)
        raise
    finally:
        db.close()
