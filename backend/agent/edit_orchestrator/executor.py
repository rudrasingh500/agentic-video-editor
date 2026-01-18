"""Operation Executor: Maps TimelineOperation to timeline_editor calls.

This module provides a bridge between the sub-agent's TimelineOperation output
and the actual timeline_editor functions that modify the timeline.
"""

from __future__ import annotations

import logging
from typing import Any, Callable
from uuid import UUID

from sqlalchemy.orm import Session as DBSession

from database.models import TimelineCheckpoint as TimelineCheckpointModel
from models.timeline_models import (
    EffectType,
    Effect,
    LinearTimeWarp,
    FreezeFrame,
    MarkerColor,
    RationalTime,
    TimeRange,
    TrackKind,
    TransitionType,
)
from operators import timeline_editor
from operators.timeline_operator import InvalidOperationError

from .sub_agents.types import EDLPatch, TimelineOperation

logger = logging.getLogger(__name__)


class OperationExecutionError(Exception):
    """Raised when an operation cannot be executed."""

    def __init__(self, operation_type: str, message: str, details: dict | None = None):
        self.operation_type = operation_type
        self.message = message
        self.details = details or {}
        super().__init__(f"{operation_type}: {message}")


class ExecutionResult:
    """Result of executing a single operation."""

    def __init__(
        self,
        operation_type: str,
        success: bool,
        checkpoint: TimelineCheckpointModel | None = None,
        error: str | None = None,
        new_version: int | None = None,
    ):
        self.operation_type = operation_type
        self.success = success
        self.checkpoint = checkpoint
        self.error = error
        self.new_version = new_version


class BatchExecutionResult:
    """Result of executing multiple operations."""

    def __init__(self):
        self.results: list[ExecutionResult] = []
        self.final_version: int | None = None
        self.total_operations: int = 0
        self.successful_operations: int = 0
        self.failed_operations: int = 0
        self.errors: list[str] = []

    @property
    def success(self) -> bool:
        return self.failed_operations == 0

    def add_result(self, result: ExecutionResult):
        self.results.append(result)
        self.total_operations += 1
        if result.success:
            self.successful_operations += 1
            if result.new_version is not None:
                self.final_version = result.new_version
        else:
            self.failed_operations += 1
            if result.error:
                self.errors.append(f"{result.operation_type}: {result.error}")


# Type aliases for operation handlers
OperationHandler = Callable[
    [DBSession, UUID, dict[str, Any], str, int], TimelineCheckpointModel
]


def _parse_rational_time(data: dict[str, Any] | None) -> RationalTime | None:
    """Parse a RationalTime from dict data."""
    if data is None:
        return None
    return RationalTime(
        value=data.get("value", 0),
        rate=data.get("rate", 24.0),
    )


def _parse_time_range(data: dict[str, Any] | None) -> TimeRange | None:
    """Parse a TimeRange from dict data."""
    if data is None:
        return None
    start_time = _parse_rational_time(data.get("start_time"))
    duration = _parse_rational_time(data.get("duration"))
    if start_time is None or duration is None:
        return None
    return TimeRange(start_time=start_time, duration=duration)


def _parse_track_kind(kind_str: str | None) -> TrackKind:
    """Parse TrackKind from string."""
    if kind_str is None:
        return TrackKind.VIDEO
    try:
        return TrackKind(kind_str)
    except ValueError:
        return TrackKind.VIDEO


def _parse_transition_type(type_str: str | None) -> TransitionType:
    """Parse TransitionType from string."""
    if type_str is None:
        return TransitionType.SMPTE_DISSOLVE
    try:
        return TransitionType(type_str)
    except ValueError:
        return TransitionType.SMPTE_DISSOLVE


def _parse_marker_color(color_str: str | None) -> MarkerColor:
    """Parse MarkerColor from string."""
    if color_str is None:
        return MarkerColor.RED
    try:
        return MarkerColor(color_str)
    except ValueError:
        return MarkerColor.RED


def _parse_effect(data: dict[str, Any] | None) -> EffectType | None:
    """Parse an EffectType from dict data."""
    if data is None:
        return None

    schema = data.get("OTIO_SCHEMA", "Effect.1")

    if schema == "LinearTimeWarp.1":
        return LinearTimeWarp(
            name=data.get("name", ""),
            effect_name=data.get("effect_name", "LinearTimeWarp"),
            time_scalar=data.get("time_scalar", 1.0),
            metadata=data.get("metadata", {}),
        )
    elif schema == "FreezeFrame.1":
        return FreezeFrame(
            name=data.get("name", ""),
            effect_name=data.get("effect_name", "FreezeFrame"),
            metadata=data.get("metadata", {}),
        )
    else:
        return Effect(
            name=data.get("name", ""),
            effect_name=data.get("effect_name", ""),
            metadata=data.get("metadata", {}),
        )


# Operation handler implementations


def _execute_add_track(
    db: DBSession,
    timeline_id: UUID,
    data: dict[str, Any],
    actor: str,
    expected_version: int,
) -> TimelineCheckpointModel:
    """Execute add_track operation."""
    return timeline_editor.add_track(
        db=db,
        timeline_id=timeline_id,
        name=data.get("name", "New Track"),
        kind=_parse_track_kind(data.get("kind")),
        index=data.get("index"),
        actor=actor,
        expected_version=expected_version,
    )


def _execute_remove_track(
    db: DBSession,
    timeline_id: UUID,
    data: dict[str, Any],
    actor: str,
    expected_version: int,
) -> TimelineCheckpointModel:
    """Execute remove_track operation."""
    track_index = data.get("track_index")
    if track_index is None:
        raise OperationExecutionError(
            "remove_track", "track_index is required", data
        )
    return timeline_editor.remove_track(
        db=db,
        timeline_id=timeline_id,
        track_index=track_index,
        actor=actor,
        expected_version=expected_version,
    )


def _execute_rename_track(
    db: DBSession,
    timeline_id: UUID,
    data: dict[str, Any],
    actor: str,
    expected_version: int,
) -> TimelineCheckpointModel:
    """Execute rename_track operation."""
    track_index = data.get("track_index")
    new_name = data.get("new_name")
    if track_index is None or new_name is None:
        raise OperationExecutionError(
            "rename_track", "track_index and new_name are required", data
        )
    return timeline_editor.rename_track(
        db=db,
        timeline_id=timeline_id,
        track_index=track_index,
        new_name=new_name,
        actor=actor,
        expected_version=expected_version,
    )


def _execute_reorder_tracks(
    db: DBSession,
    timeline_id: UUID,
    data: dict[str, Any],
    actor: str,
    expected_version: int,
) -> TimelineCheckpointModel:
    """Execute reorder_tracks operation."""
    new_order = data.get("new_order")
    if new_order is None:
        raise OperationExecutionError(
            "reorder_tracks", "new_order is required", data
        )
    return timeline_editor.reorder_tracks(
        db=db,
        timeline_id=timeline_id,
        new_order=new_order,
        actor=actor,
        expected_version=expected_version,
    )


def _execute_add_clip(
    db: DBSession,
    timeline_id: UUID,
    data: dict[str, Any],
    actor: str,
    expected_version: int,
) -> TimelineCheckpointModel:
    """Execute add_clip operation."""
    track_index = data.get("track_index")
    asset_id_str = data.get("asset_id")
    source_range_data = data.get("source_range")

    if track_index is None:
        raise OperationExecutionError("add_clip", "track_index is required", data)
    if asset_id_str is None:
        raise OperationExecutionError("add_clip", "asset_id is required", data)
    if source_range_data is None:
        raise OperationExecutionError("add_clip", "source_range is required", data)

    source_range = _parse_time_range(source_range_data)
    if source_range is None:
        raise OperationExecutionError(
            "add_clip", "Invalid source_range format", data
        )

    return timeline_editor.add_clip(
        db=db,
        timeline_id=timeline_id,
        track_index=track_index,
        asset_id=UUID(asset_id_str),
        source_range=source_range,
        insert_index=data.get("insert_index"),
        name=data.get("name"),
        actor=actor,
        expected_version=expected_version,
    )


def _execute_remove_clip(
    db: DBSession,
    timeline_id: UUID,
    data: dict[str, Any],
    actor: str,
    expected_version: int,
) -> TimelineCheckpointModel:
    """Execute remove_clip operation."""
    track_index = data.get("track_index")
    clip_index = data.get("clip_index")
    if track_index is None or clip_index is None:
        raise OperationExecutionError(
            "remove_clip", "track_index and clip_index are required", data
        )
    return timeline_editor.remove_clip(
        db=db,
        timeline_id=timeline_id,
        track_index=track_index,
        clip_index=clip_index,
        actor=actor,
        expected_version=expected_version,
    )


def _execute_trim_clip(
    db: DBSession,
    timeline_id: UUID,
    data: dict[str, Any],
    actor: str,
    expected_version: int,
) -> TimelineCheckpointModel:
    """Execute trim_clip operation."""
    track_index = data.get("track_index")
    clip_index = data.get("clip_index")
    new_source_range_data = data.get("new_source_range")

    if track_index is None or clip_index is None:
        raise OperationExecutionError(
            "trim_clip", "track_index and clip_index are required", data
        )
    if new_source_range_data is None:
        raise OperationExecutionError(
            "trim_clip", "new_source_range is required", data
        )

    new_source_range = _parse_time_range(new_source_range_data)
    if new_source_range is None:
        raise OperationExecutionError(
            "trim_clip", "Invalid new_source_range format", data
        )

    return timeline_editor.trim_clip(
        db=db,
        timeline_id=timeline_id,
        track_index=track_index,
        clip_index=clip_index,
        new_source_range=new_source_range,
        actor=actor,
        expected_version=expected_version,
    )


def _execute_slip_clip(
    db: DBSession,
    timeline_id: UUID,
    data: dict[str, Any],
    actor: str,
    expected_version: int,
) -> TimelineCheckpointModel:
    """Execute slip_clip operation."""
    track_index = data.get("track_index")
    clip_index = data.get("clip_index")
    offset_data = data.get("offset")

    if track_index is None or clip_index is None:
        raise OperationExecutionError(
            "slip_clip", "track_index and clip_index are required", data
        )
    if offset_data is None:
        raise OperationExecutionError("slip_clip", "offset is required", data)

    offset = _parse_rational_time(offset_data)
    if offset is None:
        raise OperationExecutionError("slip_clip", "Invalid offset format", data)

    return timeline_editor.slip_clip(
        db=db,
        timeline_id=timeline_id,
        track_index=track_index,
        clip_index=clip_index,
        offset=offset,
        actor=actor,
        expected_version=expected_version,
    )


def _execute_move_clip(
    db: DBSession,
    timeline_id: UUID,
    data: dict[str, Any],
    actor: str,
    expected_version: int,
) -> TimelineCheckpointModel:
    """Execute move_clip operation."""
    from_track = data.get("from_track")
    from_index = data.get("from_index")
    to_track = data.get("to_track")
    to_index = data.get("to_index")

    if any(v is None for v in [from_track, from_index, to_track, to_index]):
        raise OperationExecutionError(
            "move_clip",
            "from_track, from_index, to_track, and to_index are required",
            data,
        )

    return timeline_editor.move_clip(
        db=db,
        timeline_id=timeline_id,
        from_track=from_track,
        from_index=from_index,
        to_track=to_track,
        to_index=to_index,
        actor=actor,
        expected_version=expected_version,
    )


def _execute_replace_clip_media(
    db: DBSession,
    timeline_id: UUID,
    data: dict[str, Any],
    actor: str,
    expected_version: int,
) -> TimelineCheckpointModel:
    """Execute replace_clip_media operation."""
    track_index = data.get("track_index")
    clip_index = data.get("clip_index")
    new_asset_id_str = data.get("new_asset_id")

    if track_index is None or clip_index is None:
        raise OperationExecutionError(
            "replace_clip_media",
            "track_index and clip_index are required",
            data,
        )
    if new_asset_id_str is None:
        raise OperationExecutionError(
            "replace_clip_media", "new_asset_id is required", data
        )

    return timeline_editor.replace_clip_media(
        db=db,
        timeline_id=timeline_id,
        track_index=track_index,
        clip_index=clip_index,
        new_asset_id=UUID(new_asset_id_str),
        actor=actor,
        expected_version=expected_version,
    )


def _execute_add_gap(
    db: DBSession,
    timeline_id: UUID,
    data: dict[str, Any],
    actor: str,
    expected_version: int,
) -> TimelineCheckpointModel:
    """Execute add_gap operation."""
    track_index = data.get("track_index")
    duration_data = data.get("duration")

    if track_index is None:
        raise OperationExecutionError("add_gap", "track_index is required", data)
    if duration_data is None:
        raise OperationExecutionError("add_gap", "duration is required", data)

    duration = _parse_rational_time(duration_data)
    if duration is None:
        raise OperationExecutionError("add_gap", "Invalid duration format", data)

    return timeline_editor.add_gap(
        db=db,
        timeline_id=timeline_id,
        track_index=track_index,
        duration=duration,
        insert_index=data.get("insert_index"),
        name=data.get("name", ""),
        actor=actor,
        expected_version=expected_version,
    )


def _execute_remove_gap(
    db: DBSession,
    timeline_id: UUID,
    data: dict[str, Any],
    actor: str,
    expected_version: int,
) -> TimelineCheckpointModel:
    """Execute remove_gap operation."""
    track_index = data.get("track_index")
    gap_index = data.get("gap_index")

    if track_index is None or gap_index is None:
        raise OperationExecutionError(
            "remove_gap", "track_index and gap_index are required", data
        )

    return timeline_editor.remove_gap(
        db=db,
        timeline_id=timeline_id,
        track_index=track_index,
        gap_index=gap_index,
        actor=actor,
        expected_version=expected_version,
    )


def _execute_adjust_gap_duration(
    db: DBSession,
    timeline_id: UUID,
    data: dict[str, Any],
    actor: str,
    expected_version: int,
) -> TimelineCheckpointModel:
    """Execute adjust_gap_duration operation."""
    track_index = data.get("track_index")
    gap_index = data.get("gap_index")
    new_duration_data = data.get("new_duration")

    if track_index is None or gap_index is None:
        raise OperationExecutionError(
            "adjust_gap_duration",
            "track_index and gap_index are required",
            data,
        )
    if new_duration_data is None:
        raise OperationExecutionError(
            "adjust_gap_duration", "new_duration is required", data
        )

    new_duration = _parse_rational_time(new_duration_data)
    if new_duration is None:
        raise OperationExecutionError(
            "adjust_gap_duration", "Invalid new_duration format", data
        )

    return timeline_editor.adjust_gap_duration(
        db=db,
        timeline_id=timeline_id,
        track_index=track_index,
        gap_index=gap_index,
        new_duration=new_duration,
        actor=actor,
        expected_version=expected_version,
    )


def _execute_add_transition(
    db: DBSession,
    timeline_id: UUID,
    data: dict[str, Any],
    actor: str,
    expected_version: int,
) -> TimelineCheckpointModel:
    """Execute add_transition operation."""
    track_index = data.get("track_index")
    position = data.get("position")

    if track_index is None or position is None:
        raise OperationExecutionError(
            "add_transition", "track_index and position are required", data
        )

    in_offset = _parse_rational_time(data.get("in_offset"))
    out_offset = _parse_rational_time(data.get("out_offset"))

    return timeline_editor.add_transition(
        db=db,
        timeline_id=timeline_id,
        track_index=track_index,
        position=position,
        transition_type=_parse_transition_type(data.get("transition_type")),
        in_offset=in_offset,
        out_offset=out_offset,
        actor=actor,
        expected_version=expected_version,
    )


def _execute_remove_transition(
    db: DBSession,
    timeline_id: UUID,
    data: dict[str, Any],
    actor: str,
    expected_version: int,
) -> TimelineCheckpointModel:
    """Execute remove_transition operation."""
    track_index = data.get("track_index")
    transition_index = data.get("transition_index")

    if track_index is None or transition_index is None:
        raise OperationExecutionError(
            "remove_transition",
            "track_index and transition_index are required",
            data,
        )

    return timeline_editor.remove_transition(
        db=db,
        timeline_id=timeline_id,
        track_index=track_index,
        transition_index=transition_index,
        actor=actor,
        expected_version=expected_version,
    )


def _execute_modify_transition(
    db: DBSession,
    timeline_id: UUID,
    data: dict[str, Any],
    actor: str,
    expected_version: int,
) -> TimelineCheckpointModel:
    """Execute modify_transition operation."""
    track_index = data.get("track_index")
    transition_index = data.get("transition_index")

    if track_index is None or transition_index is None:
        raise OperationExecutionError(
            "modify_transition",
            "track_index and transition_index are required",
            data,
        )

    transition_type = None
    if data.get("transition_type"):
        transition_type = _parse_transition_type(data.get("transition_type"))

    return timeline_editor.modify_transition(
        db=db,
        timeline_id=timeline_id,
        track_index=track_index,
        transition_index=transition_index,
        transition_type=transition_type,
        in_offset=_parse_rational_time(data.get("in_offset")),
        out_offset=_parse_rational_time(data.get("out_offset")),
        actor=actor,
        expected_version=expected_version,
    )


def _execute_nest_clips_as_stack(
    db: DBSession,
    timeline_id: UUID,
    data: dict[str, Any],
    actor: str,
    expected_version: int,
) -> TimelineCheckpointModel:
    """Execute nest_clips_as_stack operation."""
    track_index = data.get("track_index")
    start_index = data.get("start_index")
    end_index = data.get("end_index")
    stack_name = data.get("stack_name")

    if any(v is None for v in [track_index, start_index, end_index, stack_name]):
        raise OperationExecutionError(
            "nest_clips_as_stack",
            "track_index, start_index, end_index, and stack_name are required",
            data,
        )

    return timeline_editor.nest_clips_as_stack(
        db=db,
        timeline_id=timeline_id,
        track_index=track_index,
        start_index=start_index,
        end_index=end_index,
        stack_name=stack_name,
        actor=actor,
        expected_version=expected_version,
    )


def _execute_flatten_nested_stack(
    db: DBSession,
    timeline_id: UUID,
    data: dict[str, Any],
    actor: str,
    expected_version: int,
) -> TimelineCheckpointModel:
    """Execute flatten_nested_stack operation."""
    track_index = data.get("track_index")
    stack_index = data.get("stack_index")

    if track_index is None or stack_index is None:
        raise OperationExecutionError(
            "flatten_nested_stack",
            "track_index and stack_index are required",
            data,
        )

    return timeline_editor.flatten_nested_stack(
        db=db,
        timeline_id=timeline_id,
        track_index=track_index,
        stack_index=stack_index,
        actor=actor,
        expected_version=expected_version,
    )


def _execute_add_marker(
    db: DBSession,
    timeline_id: UUID,
    data: dict[str, Any],
    actor: str,
    expected_version: int,
) -> TimelineCheckpointModel:
    """Execute add_marker operation."""
    track_index = data.get("track_index")
    item_index = data.get("item_index")
    marked_range_data = data.get("marked_range")

    if track_index is None or item_index is None:
        raise OperationExecutionError(
            "add_marker", "track_index and item_index are required", data
        )
    if marked_range_data is None:
        raise OperationExecutionError("add_marker", "marked_range is required", data)

    marked_range = _parse_time_range(marked_range_data)
    if marked_range is None:
        raise OperationExecutionError(
            "add_marker", "Invalid marked_range format", data
        )

    return timeline_editor.add_marker(
        db=db,
        timeline_id=timeline_id,
        track_index=track_index,
        item_index=item_index,
        marked_range=marked_range,
        name=data.get("name", ""),
        color=_parse_marker_color(data.get("color")),
        metadata=data.get("metadata"),
        actor=actor,
        expected_version=expected_version,
    )


def _execute_remove_marker(
    db: DBSession,
    timeline_id: UUID,
    data: dict[str, Any],
    actor: str,
    expected_version: int,
) -> TimelineCheckpointModel:
    """Execute remove_marker operation."""
    track_index = data.get("track_index")
    item_index = data.get("item_index")
    marker_index = data.get("marker_index")

    if any(v is None for v in [track_index, item_index, marker_index]):
        raise OperationExecutionError(
            "remove_marker",
            "track_index, item_index, and marker_index are required",
            data,
        )

    return timeline_editor.remove_marker(
        db=db,
        timeline_id=timeline_id,
        track_index=track_index,
        item_index=item_index,
        marker_index=marker_index,
        actor=actor,
        expected_version=expected_version,
    )


def _execute_add_effect(
    db: DBSession,
    timeline_id: UUID,
    data: dict[str, Any],
    actor: str,
    expected_version: int,
) -> TimelineCheckpointModel:
    """Execute add_effect operation."""
    track_index = data.get("track_index")
    item_index = data.get("item_index")
    effect_data = data.get("effect")

    if track_index is None or item_index is None:
        raise OperationExecutionError(
            "add_effect", "track_index and item_index are required", data
        )
    if effect_data is None:
        raise OperationExecutionError("add_effect", "effect is required", data)

    effect = _parse_effect(effect_data)
    if effect is None:
        raise OperationExecutionError("add_effect", "Invalid effect format", data)

    return timeline_editor.add_effect(
        db=db,
        timeline_id=timeline_id,
        track_index=track_index,
        item_index=item_index,
        effect=effect,
        actor=actor,
        expected_version=expected_version,
    )


def _execute_remove_effect(
    db: DBSession,
    timeline_id: UUID,
    data: dict[str, Any],
    actor: str,
    expected_version: int,
) -> TimelineCheckpointModel:
    """Execute remove_effect operation."""
    track_index = data.get("track_index")
    item_index = data.get("item_index")
    effect_index = data.get("effect_index")

    if any(v is None for v in [track_index, item_index, effect_index]):
        raise OperationExecutionError(
            "remove_effect",
            "track_index, item_index, and effect_index are required",
            data,
        )

    return timeline_editor.remove_effect(
        db=db,
        timeline_id=timeline_id,
        track_index=track_index,
        item_index=item_index,
        effect_index=effect_index,
        actor=actor,
        expected_version=expected_version,
    )


def _execute_clear_track(
    db: DBSession,
    timeline_id: UUID,
    data: dict[str, Any],
    actor: str,
    expected_version: int,
) -> TimelineCheckpointModel:
    """Execute clear_track operation."""
    track_index = data.get("track_index")

    if track_index is None:
        raise OperationExecutionError("clear_track", "track_index is required", data)

    return timeline_editor.clear_track(
        db=db,
        timeline_id=timeline_id,
        track_index=track_index,
        actor=actor,
        expected_version=expected_version,
    )


# Registry of operation handlers
OPERATION_HANDLERS: dict[str, OperationHandler] = {
    "add_track": _execute_add_track,
    "remove_track": _execute_remove_track,
    "rename_track": _execute_rename_track,
    "reorder_tracks": _execute_reorder_tracks,
    "add_clip": _execute_add_clip,
    "remove_clip": _execute_remove_clip,
    "trim_clip": _execute_trim_clip,
    "slip_clip": _execute_slip_clip,
    "move_clip": _execute_move_clip,
    "replace_clip_media": _execute_replace_clip_media,
    "add_gap": _execute_add_gap,
    "remove_gap": _execute_remove_gap,
    "adjust_gap_duration": _execute_adjust_gap_duration,
    "add_transition": _execute_add_transition,
    "remove_transition": _execute_remove_transition,
    "modify_transition": _execute_modify_transition,
    "nest_clips_as_stack": _execute_nest_clips_as_stack,
    "flatten_nested_stack": _execute_flatten_nested_stack,
    "add_marker": _execute_add_marker,
    "remove_marker": _execute_remove_marker,
    "add_effect": _execute_add_effect,
    "remove_effect": _execute_remove_effect,
    "clear_track": _execute_clear_track,
}


def execute_operation(
    db: DBSession,
    timeline_id: UUID,
    operation: TimelineOperation,
    actor: str = "agent",
    expected_version: int = 0,
) -> ExecutionResult:
    """Execute a single timeline operation.

    Args:
        db: Database session
        timeline_id: ID of the timeline to modify
        operation: The operation to execute
        actor: Actor name for audit trail
        expected_version: Expected timeline version (for optimistic locking)

    Returns:
        ExecutionResult with success/failure status and checkpoint if successful
    """
    op_type = operation.operation_type
    handler = OPERATION_HANDLERS.get(op_type)

    if handler is None:
        return ExecutionResult(
            operation_type=op_type,
            success=False,
            error=f"Unknown operation type: {op_type}",
        )

    try:
        checkpoint = handler(
            db, timeline_id, operation.operation_data, actor, expected_version
        )
        return ExecutionResult(
            operation_type=op_type,
            success=True,
            checkpoint=checkpoint,
            new_version=checkpoint.version,
        )
    except OperationExecutionError as e:
        logger.warning(f"Operation execution error: {e}")
        return ExecutionResult(
            operation_type=op_type,
            success=False,
            error=e.message,
        )
    except InvalidOperationError as e:
        logger.warning(f"Invalid operation: {e}")
        return ExecutionResult(
            operation_type=op_type,
            success=False,
            error=str(e),
        )
    except Exception as e:
        logger.exception(f"Unexpected error executing {op_type}")
        return ExecutionResult(
            operation_type=op_type,
            success=False,
            error=f"Unexpected error: {str(e)}",
        )


def execute_patch(
    db: DBSession,
    timeline_id: UUID,
    patch: EDLPatch,
    actor: str = "agent",
    starting_version: int = 0,
    stop_on_error: bool = True,
) -> BatchExecutionResult:
    """Execute all operations in an EDL patch.

    Args:
        db: Database session
        timeline_id: ID of the timeline to modify
        patch: The EDL patch containing operations to execute
        actor: Actor name for audit trail
        starting_version: Initial expected timeline version
        stop_on_error: If True, stop execution on first error

    Returns:
        BatchExecutionResult with overall status and individual results
    """
    result = BatchExecutionResult()
    current_version = starting_version

    for operation in patch.operations:
        op_result = execute_operation(
            db=db,
            timeline_id=timeline_id,
            operation=operation,
            actor=actor,
            expected_version=current_version,
        )
        result.add_result(op_result)

        if op_result.success and op_result.new_version is not None:
            current_version = op_result.new_version
        elif not op_result.success and stop_on_error:
            logger.warning(
                f"Stopping patch execution due to error in {operation.operation_type}"
            )
            break

    return result


def get_supported_operations() -> list[str]:
    """Return list of supported operation types."""
    return list(OPERATION_HANDLERS.keys())
