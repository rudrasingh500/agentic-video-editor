from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class RenderJobType(str, Enum):
    PREVIEW = "preview"
    EXPORT = "export"


class RenderJobStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RenderExecutionMode(str, Enum):
    CLOUD = "cloud"
    LOCAL = "local"


class VideoCodec(str, Enum):

    H264 = "h264"
    H265 = "h265"
    PRORES = "prores"
    VP9 = "vp9"
    AV1 = "av1"


class OutputContainer(str, Enum):
    MP4 = "mp4"
    MOV = "mov"
    MKV = "mkv"
    WEBM = "webm"


class AudioCodec(str, Enum):
    AAC = "aac"
    MP3 = "mp3"
    OPUS = "opus"


class RenderQuality(str, Enum):
    DRAFT = "draft"
    STANDARD = "standard"
    HIGH = "high"
    MAXIMUM = "maximum"


class VideoSettings(BaseModel):
    codec: VideoCodec = Field(default=VideoCodec.H264, description="Video codec")
    container: OutputContainer = Field(
        default=OutputContainer.MP4,
        description="Output container: mp4, mov, mkv, webm",
    )
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
    two_pass: bool = Field(
        default=False,
        description="Use 2-pass encoding when bitrate is provided",
    )
    color_space: str = Field(default="bt709", description="Output colorspace")
    color_primaries: str = Field(default="bt709", description="Output color primaries")
    color_trc: str = Field(default="bt709", description="Output transfer characteristics")


class AudioSettings(BaseModel):
    codec: AudioCodec = Field(default=AudioCodec.AAC, description="Audio codec")
    bitrate: str = Field(default="192k", description="Audio bitrate")
    sample_rate: int = Field(default=48000, description="Sample rate in Hz")
    channels: int = Field(default=2, description="Number of audio channels")


class RenderPreset(BaseModel):
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
        return cls(
            name="Draft Preview",
            quality=RenderQuality.DRAFT,
            video=VideoSettings(
                codec=VideoCodec.H264,
                container=OutputContainer.MP4,
                width=1280,
                height=720,
                crf=28,
                preset="veryfast",
                bitrate="3M",
            ),
            audio=AudioSettings(bitrate="128k"),
            use_gpu=False,
        )

    @classmethod
    def standard_export(cls) -> RenderPreset:
        return cls(
            name="Standard Export",
            quality=RenderQuality.STANDARD,
            video=VideoSettings(
                codec=VideoCodec.H264,
                container=OutputContainer.MP4,
                crf=23,
                preset="medium",
                bitrate="8M",
            ),
            audio=AudioSettings(bitrate="192k"),
            use_gpu=False,
        )

    @classmethod
    def high_quality_export(cls) -> RenderPreset:
        return cls(
            name="High Quality Export",
            quality=RenderQuality.HIGH,
            video=VideoSettings(
                codec=VideoCodec.H264,
                container=OutputContainer.MP4,
                crf=18,
                preset="slow",
                bitrate="15M",
            ),
            audio=AudioSettings(bitrate="256k"),
            use_gpu=True,
        )

    @classmethod
    def maximum_quality_export(cls) -> RenderPreset:
        return cls(
            name="Maximum Quality Export",
            quality=RenderQuality.MAXIMUM,
            video=VideoSettings(
                codec=VideoCodec.H265,
                container=OutputContainer.MP4,
                crf=12,
                preset="slow",
                bitrate="25M",
                pixel_format="yuv420p10le",
                two_pass=True,
            ),
            audio=AudioSettings(bitrate="320k", sample_rate=48000),
            use_gpu=False,
        )

    @classmethod
    def prores_master_export(cls) -> RenderPreset:
        return cls(
            name="ProRes Master Export",
            quality=RenderQuality.MAXIMUM,
            video=VideoSettings(
                codec=VideoCodec.PRORES,
                container=OutputContainer.MOV,
                crf=None,
                preset="slow",
                bitrate="110M",
                pixel_format="yuv422p10le",
                two_pass=False,
            ),
            audio=AudioSettings(codec=AudioCodec.AAC, bitrate="320k", sample_rate=48000),
            use_gpu=False,
        )

    @classmethod
    def vp9_streaming_export(cls) -> RenderPreset:
        return cls(
            name="VP9 Streaming Export",
            quality=RenderQuality.HIGH,
            video=VideoSettings(
                codec=VideoCodec.VP9,
                container=OutputContainer.WEBM,
                crf=30,
                preset="medium",
                bitrate="8M",
                pixel_format="yuv420p",
                two_pass=True,
            ),
            audio=AudioSettings(codec=AudioCodec.OPUS, bitrate="160k", sample_rate=48000),
            use_gpu=False,
        )

    @classmethod
    def av1_streaming_export(cls) -> RenderPreset:
        return cls(
            name="AV1 Streaming Export",
            quality=RenderQuality.HIGH,
            video=VideoSettings(
                codec=VideoCodec.AV1,
                container=OutputContainer.MKV,
                crf=29,
                preset="slow",
                bitrate="6M",
                pixel_format="yuv420p10le",
                two_pass=False,
            ),
            audio=AudioSettings(codec=AudioCodec.OPUS, bitrate="160k", sample_rate=48000),
            use_gpu=False,
        )


class RenderRequest(BaseModel):
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
    execution_mode: RenderExecutionMode | None = Field(
        default=None, description="Render execution mode (cloud or local)"
    )

    start_frame: int | None = Field(
        default=None, description="Start frame (None = beginning)"
    )
    end_frame: int | None = Field(default=None, description="End frame (None = end)")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata for the job"
    )



class CancelRenderRequest(BaseModel):
    reason: str | None = Field(default=None, description="Reason for cancellation")


class RenderJobResponse(BaseModel):
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
    execution_mode: RenderExecutionMode | None = None
    manifest_path: str | None = None
    output_path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RenderJobCreateResponse(BaseModel):
    ok: bool = True
    job: RenderJobResponse


class RenderJobListResponse(BaseModel):
    ok: bool = True
    jobs: list[RenderJobResponse]
    total: int


class RenderJobStatusResponse(BaseModel):
    ok: bool = True
    job: RenderJobResponse


class RenderJobCancelResponse(BaseModel):
    ok: bool = True
    job: RenderJobResponse


class RenderPresetsResponse(BaseModel):
    ok: bool = True
    presets: list[RenderPreset]


class RenderManifestResponse(BaseModel):
    ok: bool = True
    manifest_url: str
    manifest_path: str | None = None
    expires_in: int | None = None


class RenderUploadUrlRequest(BaseModel):
    filename: str | None = None
    content_type: str | None = None


class RenderUploadUrlResponse(BaseModel):
    ok: bool = True
    upload_url: str
    gcs_path: str
    expires_in: int | None = None


class RenderManifest(BaseModel):
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
    output_variants: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Optional additional output variants for multi-resolution exports",
    )
    execution_mode: RenderExecutionMode = Field(
        default=RenderExecutionMode.CLOUD, description="Execution mode"
    )



class RenderProgress(BaseModel):
    job_id: UUID
    status: RenderJobStatus
    progress: int = Field(ge=0, le=100)
    current_frame: int | None = None
    total_frames: int | None = None
    message: str | None = None
    error_message: str | None = None
    output_url: str | None = None
    output_size_bytes: int | None = None
