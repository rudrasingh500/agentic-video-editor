"""Types for sub-agent communication.

Each sub-agent receives a request with timeline context and returns
an EDL patch (diff) that can be applied to the timeline.
"""

from __future__ import annotations

from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class SubAgentType(str, Enum):
    """Types of specialized edit agents."""

    CUT = "cut"
    SILENCE = "silence"
    BROLL = "broll"
    CAPTIONS = "captions"
    MIX = "mix"
    COLOR = "color"
    MOTION = "motion"
    FX = "fx"


class TimelineSlice(BaseModel):
    """A portion of the timeline to operate on.

    Sub-agents determine their own scope from the full timeline,
    but this provides hints about the area of focus.
    """

    full_snapshot: dict[str, Any] = Field(
        description="Full timeline snapshot as JSON (sub-agent determines scope)"
    )
    focus_track_indices: list[int] | None = Field(
        default=None,
        description="Suggested track indices to focus on (None = all tracks)",
    )
    focus_time_range_ms: tuple[int, int] | None = Field(
        default=None,
        description="Suggested time range in milliseconds (start, end) to focus on",
    )
    current_version: int = Field(
        description="Current timeline version number"
    )


class AssetContext(BaseModel):
    """Context about an asset relevant to the edit operation."""

    asset_id: UUID
    asset_name: str
    asset_type: str
    duration_ms: int | None = None
    summary: str | None = None
    tags: list[str] = Field(default_factory=list)
    transcript: dict[str, Any] | None = None
    faces: list[dict[str, Any]] | None = None
    speakers: list[dict[str, Any]] | None = None
    scenes: list[dict[str, Any]] | None = None
    technical: dict[str, Any] | None = None


class PreviewRequest(BaseModel):
    """Request for a preview render of specific timeline region."""

    preview_id: str = Field(description="Unique identifier for this preview")
    time_range_ms: tuple[int, int] = Field(
        description="Time range to preview (start_ms, end_ms)"
    )
    track_indices: list[int] | None = Field(
        default=None,
        description="Tracks to include in preview (None = all)",
    )
    resolution_scale: float = Field(
        default=0.5,
        description="Scale factor for preview (0.5 = half resolution)",
    )


class TimelineOperation(BaseModel):
    """A single operation to apply to the timeline.

    These map to the existing timeline_editor operations.
    """

    operation_type: str = Field(
        description="Operation type (e.g., 'add_clip', 'trim_clip', 'add_transition')"
    )
    operation_data: dict[str, Any] = Field(
        description="Operation parameters"
    )


class EDLPatch(BaseModel):
    """Output from a sub-agent - changes to apply to the timeline.

    This represents a diff that can be applied to create a new
    timeline checkpoint.
    """

    operations: list[TimelineOperation] = Field(
        default_factory=list,
        description="Ordered list of operations to apply",
    )
    preview_requests: list[PreviewRequest] = Field(
        default_factory=list,
        description="Requested previews for user review",
    )
    metrics_needs: list[str] = Field(
        default_factory=list,
        description="Metrics the agent needs (e.g., 'loudness', 'motion_vectors')",
    )
    description: str = Field(
        default="",
        description="Human-readable description of changes",
    )
    estimated_duration_change_ms: int = Field(
        default=0,
        description="Estimated change in timeline duration (can be negative)",
    )


class SubAgentRequest(BaseModel):
    """Request sent to a sub-agent."""

    request_id: str = Field(description="Unique identifier for this request")
    intent: str = Field(
        description="What the sub-agent should accomplish (from orchestrator)"
    )
    timeline_slice: TimelineSlice = Field(
        description="Timeline context (sub-agent determines own scope)"
    )
    assets: list[AssetContext] = Field(
        default_factory=list,
        description="Relevant assets for this operation",
    )
    constraints: dict[str, Any] = Field(
        default_factory=dict,
        description="Agent-specific constraints and parameters",
    )
    conversation_context: str = Field(
        default="",
        description="Relevant conversation history for context",
    )


class SubAgentResponse(BaseModel):
    """Response from a sub-agent."""

    request_id: str = Field(description="Matches the request_id from SubAgentRequest")
    success: bool = Field(description="Whether the operation was successful")
    agent_type: SubAgentType = Field(description="Type of agent that produced this")
    patch: EDLPatch | None = Field(
        default=None,
        description="Timeline operations to apply (None if failed)",
    )
    reasoning: str = Field(
        default="",
        description="Explanation of decisions made",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-fatal issues encountered",
    )
    error: str | None = Field(
        default=None,
        description="Error message if success=False",
    )


# Agent-specific constraint types for documentation
class CutConstraints(BaseModel):
    """Constraints for CutAgent."""

    preserve_audio_sync: bool = True
    ripple_edit: bool = True
    minimum_clip_duration_ms: int = 100


class SilenceConstraints(BaseModel):
    """Constraints for SilenceAgent."""

    silence_threshold_db: float = -40.0
    minimum_silence_duration_ms: int = 500
    padding_ms: int = 100
    preserve_breaths: bool = True


class BrollConstraints(BaseModel):
    """Constraints for BrollAgent."""

    maintain_dialogue_continuity: bool = True
    preferred_broll_duration_ms: int = 3000
    allow_pip: bool = True
    blur_sensitivity: str = "medium"


class CaptionsConstraints(BaseModel):
    """Constraints for CaptionsAgent."""

    max_characters_per_line: int = 42
    max_lines: int = 2
    position: str = "bottom_center"
    style_preset: str = "default"


class MixConstraints(BaseModel):
    """Constraints for MixAgent."""

    target_loudness_lufs: float = -14.0
    dialogue_priority: bool = True
    enable_ducking: bool = True
    duck_amount_db: float = -12.0


class ColorConstraints(BaseModel):
    """Constraints for ColorAgent."""

    global_look_lut: str | None = None
    match_reference_clip: str | None = None
    white_balance_mode: str = "auto"


class MotionConstraints(BaseModel):
    """Constraints for MotionAgent."""

    stabilization_strength: float = 0.5
    auto_reframe_aspect: str | None = None
    smooth_zoom: bool = True


class FXConstraints(BaseModel):
    """Constraints for FXAgent."""

    transition_style: str = "subtle"
    speed_ramp_smoothness: float = 0.7
    allow_freeze_frames: bool = True
