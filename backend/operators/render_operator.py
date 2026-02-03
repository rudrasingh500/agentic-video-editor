from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from uuid import UUID


from sqlalchemy.orm import Session as DBSession

from database.models import (
    Assets,
    RenderJob as RenderJobModel,
    Timeline as TimelineModel,
    TimelineCheckpoint as TimelineCheckpointModel,
)
from models.render_models import (
    RenderExecutionMode,
    RenderJobResponse,
    RenderJobStatus,
    RenderJobType,
    RenderManifest,
    RenderPreset,
    RenderRequest,
)

from models.timeline_models import Timeline
from utils.cloud_run_jobs import (
    JobExecutionRequest,
    get_cloud_run_client,
)
from utils.gcs_utils import upload_file

logger = logging.getLogger(__name__)


GCS_BUCKET = os.getenv("GCS_BUCKET", "video-editor")
GCS_RENDER_BUCKET = os.getenv("GCS_RENDER_BUCKET", "video-editor-renders")


class RenderError(Exception):
    pass


class RenderJobNotFoundError(RenderError):
    def __init__(self, job_id: UUID):
        self.job_id = job_id
        super().__init__(f"Render job not found: {job_id}")


class RenderValidationError(RenderError):
    pass


class TimelineNotFoundError(RenderError):
    def __init__(self, project_id: UUID):
        self.project_id = project_id
        super().__init__(f"No timeline found for project: {project_id}")


class MissingAssetsError(RenderError):
    def __init__(self, missing_asset_ids: list[str]):
        self.missing_asset_ids = missing_asset_ids
        super().__init__(f"Missing assets: {', '.join(missing_asset_ids)}")


def create_render_job(
    db: DBSession,
    project_id: UUID,
    request: RenderRequest,
    created_by: str = "user",
) -> RenderJobModel:
    timeline_record = (
        db.query(TimelineModel).filter(TimelineModel.project_id == project_id).first()
    )
    if not timeline_record:
        raise TimelineNotFoundError(project_id)

    timeline_version = (
        request.timeline_version
        if request.timeline_version is not None
        else timeline_record.current_version
    )

    checkpoint = (
        db.query(TimelineCheckpointModel)
        .filter(
            TimelineCheckpointModel.timeline_id == timeline_record.timeline_id,
            TimelineCheckpointModel.version == timeline_version,
        )
        .first()
    )
    if not checkpoint:
        raise RenderValidationError(f"Timeline version {timeline_version} not found")

    timeline = Timeline.model_validate(checkpoint.snapshot)

    if not timeline.tracks.children:
        raise RenderValidationError("Timeline has no tracks to render")

    clips = timeline.find_clips()
    if not clips:
        raise RenderValidationError("Timeline has no clips to render")

    if request.preset:
        preset = request.preset
    elif request.job_type == RenderJobType.PREVIEW:
        preset = RenderPreset.draft_preview()
    else:
        preset = RenderPreset.standard_export()

    total_frames = _calculate_total_frames(timeline, preset)

    output_filename = request.output_filename
    if not output_filename:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        job_type = request.job_type.value
        output_filename = f"{job_type}_{timeline_version}_{timestamp}.mp4"

    execution_mode = request.execution_mode
    if execution_mode is None:
        env_mode = os.getenv("RENDER_EXECUTION_MODE", RenderExecutionMode.LOCAL.value)
        execution_mode = (
            RenderExecutionMode.LOCAL
            if env_mode.lower() == RenderExecutionMode.LOCAL.value
            else RenderExecutionMode.CLOUD
        )

    job_metadata = {
        "created_by": created_by,
        "start_frame": request.start_frame,
        "end_frame": request.end_frame,
        "execution_mode": execution_mode.value,
        **request.metadata,
    }

    job = RenderJobModel(
        project_id=project_id,
        timeline_id=timeline_record.timeline_id,
        timeline_version=timeline_version,
        job_type=request.job_type.value,
        status=RenderJobStatus.PENDING.value,
        progress=0,
        total_frames=total_frames,
        preset=preset.model_dump(),
        output_filename=output_filename,
        job_metadata=job_metadata,
    )

    db.add(job)
    db.commit()
    db.refresh(job)

    logger.info(f"Created render job {job.job_id} for project {project_id}")

    return job


def dispatch_render_job(
    db: DBSession,
    job_id: UUID,
) -> RenderJobModel:
    job = get_render_job(db, job_id)
    if not job:
        raise RenderJobNotFoundError(job_id)

    if job.status != RenderJobStatus.PENDING.value:
        raise RenderError(f"Job {job_id} is not in pending state: {job.status}")

    checkpoint = (
        db.query(TimelineCheckpointModel)
        .filter(
            TimelineCheckpointModel.timeline_id == job.timeline_id,
            TimelineCheckpointModel.version == job.timeline_version,
        )
        .first()
    )
    if not checkpoint:
        raise RenderError(f"Timeline checkpoint not found for job {job_id}")

    timeline = Timeline.model_validate(checkpoint.snapshot)

    asset_map = _build_asset_map(db, job.project_id, timeline)  # type: ignore[arg-type]


    preset = RenderPreset.model_validate(job.preset)
    output_path = f"{job.project_id}/renders/{job.output_filename}"

    job_metadata = job.job_metadata or {}
    execution_mode = str(
        job_metadata.get("execution_mode", RenderExecutionMode.LOCAL.value)
    )

    manifest = RenderManifest(
        job_id=job.job_id,
        project_id=job.project_id,
        timeline_version=job.timeline_version,
        timeline_snapshot=checkpoint.snapshot,
        asset_map=asset_map,
        preset=preset,
        input_bucket=GCS_BUCKET,
        output_bucket=GCS_RENDER_BUCKET,
        output_path=output_path,
        start_frame=job.job_metadata.get("start_frame"),
        end_frame=job.job_metadata.get("end_frame"),
        callback_url=job.job_metadata.get("callback_url"),
        execution_mode=RenderExecutionMode(execution_mode),
    )


    manifest_path = f"{job.project_id}/manifests/{job.job_id}.json"
    manifest_json = manifest.model_dump_json()

    job_metadata.update(
        {
            "manifest_path": manifest_path,
            "output_path": output_path,
            "output_bucket": GCS_RENDER_BUCKET,
            "execution_mode": execution_mode,
        }
    )
    job.job_metadata = job_metadata

    try:
        upload_info = upload_file(
            bucket_name=GCS_BUCKET,
            contents=manifest_json.encode("utf-8"),
            destination_blob_name=manifest_path,
        )
        if not upload_info:
            raise RenderError("Failed to upload render manifest")
    except Exception as e:
        logger.error(f"Failed to upload manifest for job {job_id}: {e}")
        job.status = RenderJobStatus.FAILED.value
        job.error_message = f"Failed to upload render manifest: {e}"
        db.commit()
        raise RenderError(f"Failed to upload manifest: {e}")

    manifest_ref = f"gs://{GCS_BUCKET}/{manifest_path}"

    if execution_mode.lower() == RenderExecutionMode.LOCAL.value:
        job.status = RenderJobStatus.QUEUED.value
        job.cloud_run_job_name = None
        job.cloud_run_execution_id = None
        db.commit()
        db.refresh(job)
        logger.info(f"Render job {job_id} queued for local execution")
        return job

    client = get_cloud_run_client()

    execution_request = JobExecutionRequest(
        job_id=str(job.job_id),
        manifest_gcs_path=manifest_ref,
        execution_mode=execution_mode,
        use_gpu=preset.use_gpu,
        timeout_seconds=_estimate_timeout(timeline, preset),
    )

    execution = client.execute_render_job(execution_request)

    if execution:
        job.status = RenderJobStatus.QUEUED.value
        job.cloud_run_job_name = execution.job_name
        job.cloud_run_execution_id = execution.execution_id
        job.started_at = datetime.now(timezone.utc)
    else:
        job.status = RenderJobStatus.PENDING.value
        job.error_message = "Cloud Run not available. Job queued for manual processing."

    db.commit()
    db.refresh(job)

    logger.info(
        f"Dispatched render job {job_id} to Cloud Run "
        f"(execution: {job.cloud_run_execution_id})"
    )

    return job


def get_render_job(db: DBSession, job_id: UUID) -> RenderJobModel | None:
    return db.query(RenderJobModel).filter(RenderJobModel.job_id == job_id).first()


def ensure_render_manifest(db: DBSession, job_id: UUID) -> str:
    job = get_render_job(db, job_id)
    if not job:
        raise RenderJobNotFoundError(job_id)

    metadata = job.job_metadata or {}
    manifest_path = metadata.get("manifest_path")
    if manifest_path:
        return manifest_path

    checkpoint = (
        db.query(TimelineCheckpointModel)
        .filter(
            TimelineCheckpointModel.timeline_id == job.timeline_id,
            TimelineCheckpointModel.version == job.timeline_version,
        )
        .first()
    )
    if not checkpoint:
        raise RenderError(f"Timeline checkpoint not found for job {job_id}")

    timeline = Timeline.model_validate(checkpoint.snapshot)
    asset_map = _build_asset_map(db, job.project_id, timeline)  # type: ignore[arg-type]
    preset = RenderPreset.model_validate(job.preset)

    output_path = metadata.get("output_path")
    if not output_path:
        output_filename = job.output_filename or f"{job.job_id}.mp4"
        output_path = f"{job.project_id}/renders/{output_filename}"

    execution_mode = str(
        metadata.get("execution_mode", RenderExecutionMode.LOCAL.value)
    )

    manifest = RenderManifest(
        job_id=job.job_id,
        project_id=job.project_id,
        timeline_version=job.timeline_version,
        timeline_snapshot=checkpoint.snapshot,
        asset_map=asset_map,
        preset=preset,
        input_bucket=GCS_BUCKET,
        output_bucket=GCS_RENDER_BUCKET,
        output_path=output_path,
        start_frame=metadata.get("start_frame"),
        end_frame=metadata.get("end_frame"),
        callback_url=metadata.get("callback_url"),
        execution_mode=RenderExecutionMode(execution_mode),
    )

    manifest_path = f"{job.project_id}/manifests/{job.job_id}.json"
    manifest_json = manifest.model_dump_json()

    upload_info = upload_file(
        bucket_name=GCS_BUCKET,
        contents=manifest_json.encode("utf-8"),
        destination_blob_name=manifest_path,
    )
    if not upload_info:
        raise RenderError("Failed to upload render manifest")

    metadata.update(
        {
            "manifest_path": manifest_path,
            "output_path": output_path,
            "output_bucket": GCS_RENDER_BUCKET,
            "execution_mode": execution_mode,
        }
    )
    job.job_metadata = metadata
    db.commit()
    db.refresh(job)

    return manifest_path


def list_render_jobs(
    db: DBSession,
    project_id: UUID,
    status: RenderJobStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[RenderJobModel], int]:
    query = db.query(RenderJobModel).filter(RenderJobModel.project_id == project_id)

    if status:
        query = query.filter(RenderJobModel.status == status.value)

    total = query.count()
    jobs = (
        query.order_by(RenderJobModel.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return jobs, total


def update_job_status(
    db: DBSession,
    job_id: UUID,
    status: RenderJobStatus,
    progress: int | None = None,
    current_frame: int | None = None,
    error_message: str | None = None,
    output_url: str | None = None,
    output_size_bytes: int | None = None,
) -> RenderJobModel | None:
    job = get_render_job(db, job_id)
    if not job:
        return None

    job.status = status.value

    if progress is not None:
        job.progress = progress

    if current_frame is not None:
        job.current_frame = current_frame

    if error_message:
        job.error_message = error_message

    if output_url:
        job.output_url = output_url

    if output_size_bytes:
        job.output_size_bytes = output_size_bytes

    if status in (
        RenderJobStatus.COMPLETED,
        RenderJobStatus.FAILED,
        RenderJobStatus.CANCELLED,
    ):
        job.completed_at = datetime.now(timezone.utc)

    if status == RenderJobStatus.PROCESSING and not job.started_at:
        job.started_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(job)

    return job


def cancel_render_job(
    db: DBSession,
    job_id: UUID,
    reason: str | None = None,
) -> RenderJobModel | None:
    job = get_render_job(db, job_id)
    if not job:
        return None

    if job.status not in (
        RenderJobStatus.PENDING.value,
        RenderJobStatus.QUEUED.value,
        RenderJobStatus.PROCESSING.value,
    ):
        raise RenderError(f"Cannot cancel job in {job.status} state")

    if job.cloud_run_job_name and job.cloud_run_execution_id:
        client = get_cloud_run_client()
        client.cancel_execution(job.cloud_run_job_name, job.cloud_run_execution_id)

    job.status = RenderJobStatus.CANCELLED.value
    job.error_message = reason or "Cancelled by user"
    job.completed_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(job)

    logger.info(f"Cancelled render job {job_id}: {reason}")

    return job


def poll_job_status(db: DBSession, job_id: UUID) -> RenderJobModel | None:
    job = get_render_job(db, job_id)
    if not job:
        return None

    if job.status not in (
        RenderJobStatus.QUEUED.value,
        RenderJobStatus.PROCESSING.value,
    ):
        return job

    if not job.cloud_run_job_name or not job.cloud_run_execution_id:
        return job

    client = get_cloud_run_client()
    execution = client.get_execution_status(
        job.cloud_run_job_name, job.cloud_run_execution_id
    )

    if not execution:
        return job

    status_map = {
        "PENDING": RenderJobStatus.QUEUED,
        "RUNNING": RenderJobStatus.PROCESSING,
        "SUCCEEDED": RenderJobStatus.COMPLETED,
        "FAILED": RenderJobStatus.FAILED,
        "CANCELLED": RenderJobStatus.CANCELLED,
    }

    new_status = status_map.get(execution.status)
    if new_status and new_status.value != job.status:
        return update_job_status(
            db,
            job_id,
            new_status,
            error_message=execution.error_message,
        )

    return job


def delete_render_job(db: DBSession, job_id: UUID) -> bool:
    job = get_render_job(db, job_id)
    if not job:
        return False

    db.delete(job)
    db.commit()

    return True


def _build_asset_map(
    db: DBSession,
    project_id: UUID,
    timeline: Timeline,
) -> dict[str, str]:
    from models.timeline_models import ExternalReference

    asset_map: dict[str, str] = {}
    missing: list[str] = []

    clips = timeline.find_clips()

    for clip in clips:
        if isinstance(clip.media_reference, ExternalReference):
            asset_id = str(clip.media_reference.asset_id)
            if asset_id not in asset_map:
                asset = (
                    db.query(Assets)
                    .filter(
                        Assets.asset_id == clip.media_reference.asset_id,
                        Assets.project_id == project_id,
                    )
                    .first()
                )

                if asset:
                    asset_map[asset_id] = asset.asset_url
                else:
                    missing.append(asset_id)

    if missing:
        raise MissingAssetsError(missing)

    return asset_map


def _calculate_total_frames(timeline: Timeline, preset: RenderPreset) -> int:
    duration_seconds = timeline.duration.to_seconds()
    framerate = preset.video.framerate or 24.0
    return int(duration_seconds * framerate)


def _estimate_timeout(timeline: Timeline, preset: RenderPreset) -> int:

    from utils.ffmpeg_builder import estimate_render_duration

    estimated = estimate_render_duration(timeline, preset)

    timeout = int(estimated * 1.5)
    timeout = max(300, min(timeout, 14400))

    return timeout


def render_job_to_response(job: RenderJobModel) -> RenderJobResponse:
    metadata = job.job_metadata or {}
    execution_mode = metadata.get("execution_mode")
    render_execution_mode = None
    if execution_mode:
        try:
            render_execution_mode = RenderExecutionMode(str(execution_mode))
        except ValueError:
            render_execution_mode = None
    return RenderJobResponse(
        job_id=job.job_id,
        project_id=job.project_id,
        job_type=RenderJobType(job.job_type),
        status=RenderJobStatus(job.status),
        progress=job.progress,
        timeline_version=job.timeline_version,
        preset=RenderPreset.model_validate(job.preset),
        output_filename=job.output_filename,
        output_url=job.output_url,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        cloud_run_execution_id=job.cloud_run_execution_id,
        execution_mode=render_execution_mode,
        manifest_path=metadata.get("manifest_path"),
        output_path=metadata.get("output_path"),
        metadata=metadata,
    )
