"""
Pydantic models for video rendering functionality.

This module defines request/response schemas for:
- Render job creation and management
- Render presets and quality settings
- Job status tracking
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


# =============================================================================
# ENUMS
# =============================================================================


class RenderJobType(str, Enum):
    """Type of render job."""

    PREVIEW = "preview"  # Quick, lower quality for playback
    EXPORT = "export"  # High quality final output


class RenderJobStatus(str, Enum):
    """Status of a render job."""

    PENDING = "pending"  # Job created, waiting to start
    QUEUED = "queued"  # Sent to Cloud Run, waiting for execution
    PROCESSING = "processing"  # Actively rendering
    UPLOADING = "uploading"  # Render complete, uploading to GCS
    COMPLETED = "completed"  # Successfully finished
    FAILED = "failed"  # Error occurred
    CANCELLED = "cancelled"  # User cancelled


class VideoCodec(str, Enum):
    """Supported video codecs."""

    H264 = "h264"  # libx264 (CPU) or h264_nvenc (GPU)
    H265 = "h265"  # libx265 (CPU) or hevc_nvenc (GPU)


class AudioCodec(str, Enum):
    """Supported audio codecs."""

    AAC = "aac"
    MP3 = "mp3"


class RenderQuality(str, Enum):
    """Preset quality levels."""

    DRAFT = "draft"  # Fast preview, lower quality
    STANDARD = "standard"  # Balanced quality/speed
    HIGH = "high"  # High quality, slower
    MAXIMUM = "maximum"  # Best quality, slowest


# =============================================================================
# RENDER PRESETS
# =============================================================================


class VideoSettings(BaseModel):
    """Video encoding settings."""

    codec: VideoCodec = Field(default=VideoCodec.H264, description="Video codec")
    width: int | None = Field(default=None, description="Output width (None = source)")
    height: int | None = Field(
        default=None, description="Output height (None = source)"
    )
    framerate: float | None = Field(
        default=None, description="Output framerate (None = timeline default)"
    )
    bitrate: str | None = Field(
        default=None, description="Target bitrate e.g. '10M', '5000k'"
    )
    crf: int | None = Field(
        default=23,
        ge=0,
        le=51,
        description="Constant Rate Factor (0=lossless, 23=default, 51=worst)",
    )
    preset: str = Field(
        default="medium",
        description="Encoding preset: ultrafast, superfast, veryfast, faster, fast, medium, slow, slower, veryslow",
    )
    pixel_format: str = Field(default="yuv420p", description="Pixel format")


class AudioSettings(BaseModel):
    """Audio encoding settings."""

    codec: AudioCodec = Field(default=AudioCodec.AAC, description="Audio codec")
    bitrate: str = Field(default="192k", description="Audio bitrate")
    sample_rate: int = Field(default=48000, description="Sample rate in Hz")
    channels: int = Field(default=2, description="Number of audio channels")


class RenderPreset(BaseModel):
    """Complete render preset configuration."""

    name: str = Field(description="Preset name")
    quality: RenderQuality = Field(
        default=RenderQuality.STANDARD, description="Quality level"
    )
    video: VideoSettings = Field(default_factory=VideoSettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    use_gpu: bool = Field(
        default=False, description="Use GPU acceleration if available"
    )

    @classmethod
    def draft_preview(cls) -> RenderPreset:
        """Quick preview preset - fast encoding, lower quality."""
        return cls(
            name="Draft Preview",
            quality=RenderQuality.DRAFT,
            video=VideoSettings(
                codec=VideoCodec.H264,
                width=1280,
                height=720,
                crf=28,
                preset="veryfast",
            ),
            audio=AudioSettings(bitrate="128k"),
            use_gpu=False,
        )

    @classmethod
    def standard_export(cls) -> RenderPreset:
        """Standard quality export preset."""
        return cls(
            name="Standard Export",
            quality=RenderQuality.STANDARD,
            video=VideoSettings(
                codec=VideoCodec.H264,
                crf=23,
                preset="medium",
            ),
            audio=AudioSettings(bitrate="192k"),
            use_gpu=False,
        )

    @classmethod
    def high_quality_export(cls) -> RenderPreset:
        """High quality export preset with GPU acceleration."""
        return cls(
            name="High Quality Export",
            quality=RenderQuality.HIGH,
            video=VideoSettings(
                codec=VideoCodec.H264,
                crf=18,
                preset="slow",
            ),
            audio=AudioSettings(bitrate="320k"),
            use_gpu=True,
        )

    @classmethod
    def maximum_quality_export(cls) -> RenderPreset:
        """Maximum quality export preset."""
        return cls(
            name="Maximum Quality Export",
            quality=RenderQuality.MAXIMUM,
            video=VideoSettings(
                codec=VideoCodec.H264,
                crf=15,
                preset="veryslow",
            ),
            audio=AudioSettings(bitrate="320k", sample_rate=48000),
            use_gpu=True,
        )


# =============================================================================
# REQUEST MODELS
# =============================================================================


class RenderRequest(BaseModel):
    """Request to start a render job."""

    job_type: RenderJobType = Field(
        default=RenderJobType.EXPORT, description="Type of render job"
    )
    timeline_version: int | None = Field(
        default=None, description="Timeline version to render (None = current)"
    )
    preset: RenderPreset | None = Field(
        default=None, description="Render preset (None = use default for job type)"
    )
    output_filename: str | None = Field(
        default=None, description="Output filename (auto-generated if not specified)"
    )
    # Optional time range to render (for partial renders)
    start_frame: int | None = Field(
        default=None, description="Start frame (None = beginning)"
    )
    end_frame: int | None = Field(default=None, description="End frame (None = end)")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata for the job"
    )


class CancelRenderRequest(BaseModel):
    """Request to cancel a render job."""

    reason: str | None = Field(default=None, description="Reason for cancellation")


# =============================================================================
# RESPONSE MODELS
# =============================================================================


class RenderJobResponse(BaseModel):
    """Response containing render job details."""

    job_id: UUID
    project_id: UUID
    job_type: RenderJobType
    status: RenderJobStatus
    progress: int = Field(ge=0, le=100, description="Progress percentage")
    timeline_version: int
    preset: RenderPreset
    output_filename: str | None = None
    output_url: str | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cloud_run_execution_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RenderJobCreateResponse(BaseModel):
    """Response after creating a render job."""

    ok: bool = True
    job: RenderJobResponse


class RenderJobListResponse(BaseModel):
    """Response containing list of render jobs."""

    ok: bool = True
    jobs: list[RenderJobResponse]
    total: int


class RenderJobStatusResponse(BaseModel):
    """Response for render job status check."""

    ok: bool = True
    job: RenderJobResponse


class RenderJobCancelResponse(BaseModel):
    """Response after cancelling a render job."""

    ok: bool = True
    job: RenderJobResponse


class RenderPresetsResponse(BaseModel):
    """Response containing available render presets."""

    ok: bool = True
    presets: list[RenderPreset]


# =============================================================================
# INTERNAL MODELS (for job processing)
# =============================================================================


class RenderManifest(BaseModel):
    """
    Manifest file passed to Cloud Run job.

    Contains all information needed to render the video:
    - Timeline snapshot
    - Asset mappings (asset_id -> GCS path)
    - Render settings
    - Output location
    """

    job_id: UUID
    project_id: UUID
    timeline_version: int
    timeline_snapshot: dict[str, Any] = Field(description="Timeline JSON")
    asset_map: dict[str, str] = Field(
        description="Mapping of asset_id -> GCS blob path"
    )
    preset: RenderPreset
    output_bucket: str
    output_path: str
    input_bucket: str
    start_frame: int | None = None
    end_frame: int | None = None
    callback_url: str | None = Field(
        default=None, description="URL to POST status updates"
    )


class RenderProgress(BaseModel):
    """Progress update from render job."""

    job_id: UUID
    status: RenderJobStatus
    progress: int = Field(ge=0, le=100)
    current_frame: int | None = None
    total_frames: int | None = None
    message: str | None = None
    error_message: str | None = None
