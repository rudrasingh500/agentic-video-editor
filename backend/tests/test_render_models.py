import pytest
from uuid import uuid4
from datetime import datetime, timezone

from models.render_models import (
    AudioCodec,
    AudioSettings,
    CancelRenderRequest,
    RenderJobListResponse,
    RenderJobResponse,
    RenderJobStatus,
    RenderJobType,
    RenderManifest,
    RenderPreset,
    RenderProgress,
    RenderQuality,
    RenderRequest,
    VideoCodec,
    VideoSettings,
)


class TestVideoSettings:
    def test_default_settings(self):
        settings = VideoSettings()

        assert settings.codec == VideoCodec.H264
        assert settings.width is None
        assert settings.height is None
        assert settings.crf == 23
        assert settings.preset == "medium"
        assert settings.pixel_format == "yuv420p"

    def test_custom_settings(self):
        settings = VideoSettings(
            codec=VideoCodec.H265,
            width=1920,
            height=1080,
            framerate=30.0,
            bitrate="10M",
            crf=18,
            preset="slow",
        )

        assert settings.codec == VideoCodec.H265
        assert settings.width == 1920
        assert settings.height == 1080
        assert settings.framerate == 30.0
        assert settings.bitrate == "10M"
        assert settings.crf == 18
        assert settings.preset == "slow"

    def test_crf_validation(self):
        settings = VideoSettings(crf=0)
        assert settings.crf == 0

        settings = VideoSettings(crf=51)
        assert settings.crf == 51

        with pytest.raises(ValueError):
            VideoSettings(crf=-1)

        with pytest.raises(ValueError):
            VideoSettings(crf=52)


class TestAudioSettings:
    def test_default_settings(self):
        settings = AudioSettings()

        assert settings.codec == AudioCodec.AAC
        assert settings.bitrate == "192k"
        assert settings.sample_rate == 48000
        assert settings.channels == 2

    def test_custom_settings(self):
        settings = AudioSettings(
            codec=AudioCodec.MP3,
            bitrate="320k",
            sample_rate=44100,
            channels=1,
        )

        assert settings.codec == AudioCodec.MP3
        assert settings.bitrate == "320k"
        assert settings.sample_rate == 44100
        assert settings.channels == 1


class TestRenderPreset:
    def test_default_preset(self):
        preset = RenderPreset(name="Test")

        assert preset.name == "Test"
        assert preset.quality == RenderQuality.STANDARD
        assert preset.use_gpu is False
        assert preset.video.codec == VideoCodec.H264
        assert preset.audio.codec == AudioCodec.AAC

    def test_draft_preview_factory(self):
        preset = RenderPreset.draft_preview()

        assert preset.name == "Draft Preview"
        assert preset.quality == RenderQuality.DRAFT
        assert preset.video.width == 1280
        assert preset.video.height == 720
        assert preset.video.crf == 28
        assert preset.video.preset == "veryfast"
        assert preset.audio.bitrate == "128k"
        assert preset.use_gpu is False

    def test_standard_export_factory(self):
        preset = RenderPreset.standard_export()

        assert preset.name == "Standard Export"
        assert preset.quality == RenderQuality.STANDARD
        assert preset.video.crf == 23
        assert preset.video.preset == "medium"
        assert preset.audio.bitrate == "192k"
        assert preset.use_gpu is False

    def test_high_quality_factory(self):
        preset = RenderPreset.high_quality_export()

        assert preset.name == "High Quality Export"
        assert preset.quality == RenderQuality.HIGH
        assert preset.video.crf == 18
        assert preset.video.preset == "slow"
        assert preset.audio.bitrate == "320k"
        assert preset.use_gpu is True

    def test_maximum_quality_factory(self):
        preset = RenderPreset.maximum_quality_export()

        assert preset.name == "Maximum Quality Export"
        assert preset.quality == RenderQuality.MAXIMUM
        assert preset.video.crf == 15
        assert preset.video.preset == "veryslow"
        assert preset.use_gpu is True


class TestRenderRequest:
    def test_default_request(self):
        request = RenderRequest()

        assert request.job_type == RenderJobType.EXPORT
        assert request.timeline_version is None
        assert request.preset is None
        assert request.output_filename is None
        assert request.start_frame is None
        assert request.end_frame is None
        assert request.metadata == {}

    def test_preview_request(self):
        request = RenderRequest(
            job_type=RenderJobType.PREVIEW,
            timeline_version=5,
        )

        assert request.job_type == RenderJobType.PREVIEW
        assert request.timeline_version == 5

    def test_export_request_with_preset(self):
        preset = RenderPreset.high_quality_export()

        request = RenderRequest(
            job_type=RenderJobType.EXPORT,
            preset=preset,
            output_filename="final_video.mp4",
        )

        assert request.job_type == RenderJobType.EXPORT
        assert request.preset.quality == RenderQuality.HIGH
        assert request.output_filename == "final_video.mp4"

    def test_partial_render_request(self):
        request = RenderRequest(
            start_frame=100,
            end_frame=500,
        )

        assert request.start_frame == 100
        assert request.end_frame == 500


class TestCancelRenderRequest:
    def test_cancel_without_reason(self):
        request = CancelRenderRequest()
        assert request.reason is None

    def test_cancel_with_reason(self):
        request = CancelRenderRequest(reason="User cancelled")
        assert request.reason == "User cancelled"


class TestRenderJobResponse:
    def test_job_response(self):
        job_id = uuid4()
        project_id = uuid4()

        response = RenderJobResponse(
            job_id=job_id,
            project_id=project_id,
            job_type=RenderJobType.EXPORT,
            status=RenderJobStatus.PROCESSING,
            progress=50,
            timeline_version=3,
            preset=RenderPreset.standard_export(),
            created_at=datetime.now(timezone.utc),
        )

        assert response.job_id == job_id
        assert response.project_id == project_id
        assert response.job_type == RenderJobType.EXPORT
        assert response.status == RenderJobStatus.PROCESSING
        assert response.progress == 50
        assert response.timeline_version == 3

    def test_completed_job_response(self):
        job_id = uuid4()
        project_id = uuid4()
        now = datetime.now(timezone.utc)

        response = RenderJobResponse(
            job_id=job_id,
            project_id=project_id,
            job_type=RenderJobType.EXPORT,
            status=RenderJobStatus.COMPLETED,
            progress=100,
            timeline_version=1,
            preset=RenderPreset.standard_export(),
            output_filename="render.mp4",
            output_url="gs://bucket/project/renders/render.mp4",
            created_at=now,
            started_at=now,
            completed_at=now,
        )

        assert response.status == RenderJobStatus.COMPLETED
        assert response.progress == 100
        assert response.output_url is not None
        assert response.completed_at is not None

    def test_failed_job_response(self):
        job_id = uuid4()
        project_id = uuid4()

        response = RenderJobResponse(
            job_id=job_id,
            project_id=project_id,
            job_type=RenderJobType.EXPORT,
            status=RenderJobStatus.FAILED,
            progress=30,
            timeline_version=1,
            preset=RenderPreset.standard_export(),
            error_message="FFmpeg encoding failed: invalid codec",
            created_at=datetime.now(timezone.utc),
        )

        assert response.status == RenderJobStatus.FAILED
        assert response.error_message is not None


class TestRenderJobListResponse:
    def test_empty_list(self):
        response = RenderJobListResponse(ok=True, jobs=[], total=0)

        assert response.ok is True
        assert response.jobs == []
        assert response.total == 0

    def test_list_with_jobs(self):
        job = RenderJobResponse(
            job_id=uuid4(),
            project_id=uuid4(),
            job_type=RenderJobType.EXPORT,
            status=RenderJobStatus.COMPLETED,
            progress=100,
            timeline_version=1,
            preset=RenderPreset.standard_export(),
            created_at=datetime.now(timezone.utc),
        )

        response = RenderJobListResponse(ok=True, jobs=[job], total=1)

        assert len(response.jobs) == 1
        assert response.total == 1


class TestRenderManifest:
    def test_manifest_creation(self):
        job_id = uuid4()
        project_id = uuid4()

        manifest = RenderManifest(
            job_id=job_id,
            project_id=project_id,
            timeline_version=3,
            timeline_snapshot={"name": "Test Timeline", "tracks": {}},
            asset_map={"asset-1": "project/videos/clip1.mp4"},
            preset=RenderPreset.standard_export(),
            input_bucket="video-editor-assets",
            output_bucket="video-editor-renders",
            output_path="project/renders/output.mp4",
        )

        assert manifest.job_id == job_id
        assert manifest.project_id == project_id
        assert manifest.timeline_version == 3
        assert "asset-1" in manifest.asset_map
        assert manifest.input_bucket == "video-editor-assets"
        assert manifest.output_bucket == "video-editor-renders"

    def test_manifest_with_callback(self):
        manifest = RenderManifest(
            job_id=uuid4(),
            project_id=uuid4(),
            timeline_version=1,
            timeline_snapshot={},
            asset_map={},
            preset=RenderPreset.draft_preview(),
            input_bucket="bucket",
            output_bucket="bucket",
            output_path="output.mp4",
            callback_url="https://api.example.com/webhook/render",
        )

        assert manifest.callback_url is not None

    def test_manifest_with_frame_range(self):
        manifest = RenderManifest(
            job_id=uuid4(),
            project_id=uuid4(),
            timeline_version=1,
            timeline_snapshot={},
            asset_map={},
            preset=RenderPreset.draft_preview(),
            input_bucket="bucket",
            output_bucket="bucket",
            output_path="output.mp4",
            start_frame=100,
            end_frame=500,
        )

        assert manifest.start_frame == 100
        assert manifest.end_frame == 500


class TestRenderProgress:
    def test_progress_update(self):
        progress = RenderProgress(
            job_id=uuid4(),
            status=RenderJobStatus.PROCESSING,
            progress=50,
            current_frame=500,
            total_frames=1000,
        )

        assert progress.progress == 50
        assert progress.current_frame == 500
        assert progress.total_frames == 1000

    def test_completion_update(self):
        progress = RenderProgress(
            job_id=uuid4(),
            status=RenderJobStatus.COMPLETED,
            progress=100,
            message="Render complete",
        )

        assert progress.status == RenderJobStatus.COMPLETED
        assert progress.progress == 100
        assert progress.message == "Render complete"

    def test_failure_update(self):
        progress = RenderProgress(
            job_id=uuid4(),
            status=RenderJobStatus.FAILED,
            progress=45,
            error_message="FFmpeg error: encoding failed",
        )

        assert progress.status == RenderJobStatus.FAILED
        assert progress.error_message is not None

    def test_progress_validation(self):
        progress = RenderProgress(
            job_id=uuid4(),
            status=RenderJobStatus.PROCESSING,
            progress=0,
        )
        assert progress.progress == 0

        progress = RenderProgress(
            job_id=uuid4(),
            status=RenderJobStatus.PROCESSING,
            progress=100,
        )
        assert progress.progress == 100

        with pytest.raises(ValueError):
            RenderProgress(
                job_id=uuid4(),
                status=RenderJobStatus.PROCESSING,
                progress=-1,
            )

        with pytest.raises(ValueError):
            RenderProgress(
                job_id=uuid4(),
                status=RenderJobStatus.PROCESSING,
                progress=101,
            )


class TestEnums:
    def test_job_types(self):
        assert RenderJobType.PREVIEW.value == "preview"
        assert RenderJobType.EXPORT.value == "export"

    def test_job_statuses(self):
        assert RenderJobStatus.PENDING.value == "pending"
        assert RenderJobStatus.QUEUED.value == "queued"
        assert RenderJobStatus.PROCESSING.value == "processing"
        assert RenderJobStatus.UPLOADING.value == "uploading"
        assert RenderJobStatus.COMPLETED.value == "completed"
        assert RenderJobStatus.FAILED.value == "failed"
        assert RenderJobStatus.CANCELLED.value == "cancelled"

    def test_video_codecs(self):
        assert VideoCodec.H264.value == "h264"
        assert VideoCodec.H265.value == "h265"

    def test_audio_codecs(self):
        assert AudioCodec.AAC.value == "aac"
        assert AudioCodec.MP3.value == "mp3"

    def test_quality_levels(self):
        assert RenderQuality.DRAFT.value == "draft"
        assert RenderQuality.STANDARD.value == "standard"
        assert RenderQuality.HIGH.value == "high"
        assert RenderQuality.MAXIMUM.value == "maximum"
