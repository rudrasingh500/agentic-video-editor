from copy import deepcopy
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session as DBSession

from database.models import (
    TimelineCheckpoint as TimelineCheckpointModel,
    Assets as AssetsModel,
)
from models.timeline_models import (
    Timeline,
    Stack,
    Track,
    TrackKind,
    Clip,
    Gap,
    Transition,
    TransitionType,
    RationalTime,
    TimeRange,
    ExternalReference,
    Marker,
    MarkerColor,
    EffectType,
)
from operators.timeline_operator import (
    get_timeline_snapshot,
    create_checkpoint,
    InvalidOperationError,
)


def _get_track(timeline: Timeline, track_index: int) -> Track:
    if track_index < 0 or track_index >= len(timeline.tracks.children):
        raise InvalidOperationError(
            f"Track index {track_index} out of range "
            f"(0-{len(timeline.tracks.children) - 1})"
        )
    track = timeline.tracks.children[track_index]
    if not isinstance(track, Track):
        raise InvalidOperationError(f"Item at index {track_index} is not a Track")
    return track


def _get_item_from_track(
    track: Track, item_index: int
) -> Clip | Gap | Transition | Stack:
    if item_index < 0 or item_index >= len(track.children):
        raise InvalidOperationError(
            f"Item index {item_index} out of range "
            f"(0-{len(track.children) - 1}) in track '{track.name}'"
        )
    return track.children[item_index]


def _validate_transition_position(track: Track, position: int) -> None:
    if position < 1 or position >= len(track.children):
        raise InvalidOperationError(
            f"Transition position {position} is invalid. "
            f"Must be between 1 and {len(track.children) - 1}"
        )
    prev_item = track.children[position - 1]
    next_item = track.children[position] if position < len(track.children) else None
    if isinstance(prev_item, Transition):
        raise InvalidOperationError(
            "Cannot place transition: previous item is already a transition"
        )
    if next_item and isinstance(next_item, Transition):
        raise InvalidOperationError(
            "Cannot place transition: next item is already a transition"
        )


def add_track(
    db: DBSession,
    timeline_id: UUID,
    name: str,
    kind: TrackKind = TrackKind.VIDEO,
    index: int | None = None,
    actor: str = "system",
    expected_version: int = 0,
) -> TimelineCheckpointModel:
    current = get_timeline_snapshot(db, timeline_id)
    timeline = deepcopy(current.timeline)
    new_track = Track(name=name, kind=kind, children=[])

    if index is None or index >= len(timeline.tracks.children):
        timeline.tracks.children.append(new_track)
        insert_pos = len(timeline.tracks.children) - 1
    else:
        index = max(0, index)
        timeline.tracks.children.insert(index, new_track)
        insert_pos = index

    return create_checkpoint(
        db=db,
        timeline_id=timeline_id,
        snapshot=timeline,
        description=f"Added {kind.value} track '{name}' at position {insert_pos}",
        created_by=actor,
        expected_version=expected_version,
        operation_type="add_track",
        operation_data={
            "name": name,
            "kind": kind.value,
            "index": insert_pos,
        },
    )


def remove_track(
    db: DBSession,
    timeline_id: UUID,
    track_index: int,
    actor: str = "system",
    expected_version: int = 0,
) -> TimelineCheckpointModel:
    current = get_timeline_snapshot(db, timeline_id)
    timeline = deepcopy(current.timeline)
    track = _get_track(timeline, track_index)
    track_name = track.name
    timeline.tracks.children.pop(track_index)

    return create_checkpoint(
        db=db,
        timeline_id=timeline_id,
        snapshot=timeline,
        description=f"Removed track '{track_name}' from position {track_index}",
        created_by=actor,
        expected_version=expected_version,
        operation_type="remove_track",
        operation_data={
            "track_index": track_index,
            "track_name": track_name,
        },
    )


def rename_track(
    db: DBSession,
    timeline_id: UUID,
    track_index: int,
    new_name: str,
    actor: str = "system",
    expected_version: int = 0,
) -> TimelineCheckpointModel:
    current = get_timeline_snapshot(db, timeline_id)
    timeline = deepcopy(current.timeline)
    track = _get_track(timeline, track_index)
    old_name = track.name
    track.name = new_name

    return create_checkpoint(
        db=db,
        timeline_id=timeline_id,
        snapshot=timeline,
        description=f"Renamed track '{old_name}' to '{new_name}'",
        created_by=actor,
        expected_version=expected_version,
        operation_type="rename_track",
        operation_data={
            "track_index": track_index,
            "old_name": old_name,
            "new_name": new_name,
        },
    )


def reorder_tracks(
    db: DBSession,
    timeline_id: UUID,
    new_order: list[int],
    actor: str = "system",
    expected_version: int = 0,
) -> TimelineCheckpointModel:
    current = get_timeline_snapshot(db, timeline_id)
    timeline = deepcopy(current.timeline)
    num_tracks = len(timeline.tracks.children)

    if len(new_order) != num_tracks:
        raise InvalidOperationError(
            f"new_order has {len(new_order)} elements, but there are {num_tracks} tracks"
        )
    if set(new_order) != set(range(num_tracks)):
        raise InvalidOperationError(
            f"new_order must contain each index 0-{num_tracks - 1} exactly once"
        )

    old_tracks = timeline.tracks.children.copy()
    timeline.tracks.children = [old_tracks[i] for i in new_order]

    return create_checkpoint(
        db=db,
        timeline_id=timeline_id,
        snapshot=timeline,
        description=f"Reordered tracks: {new_order}",
        created_by=actor,
        expected_version=expected_version,
        operation_type="reorder_tracks",
        operation_data={"new_order": new_order},
    )


def add_clip(
    db: DBSession,
    timeline_id: UUID,
    track_index: int,
    asset_id: UUID,
    source_range: TimeRange,
    insert_index: int | None = None,
    name: str | None = None,
    actor: str = "system",
    expected_version: int = 0,
) -> TimelineCheckpointModel:
    current = get_timeline_snapshot(db, timeline_id)
    timeline = deepcopy(current.timeline)
    track = _get_track(timeline, track_index)

    if name is None:
        asset = db.query(AssetsModel).filter(AssetsModel.asset_id == asset_id).first()
        name = asset.asset_name if asset else f"Clip-{asset_id}"

    clip = Clip(
        name=name,
        source_range=source_range,
        media_reference=ExternalReference(asset_id=asset_id),
    )

    if insert_index is None or insert_index >= len(track.children):
        track.children.append(clip)
        insert_pos = len(track.children) - 1
    else:
        insert_index = max(0, insert_index)
        track.children.insert(insert_index, clip)
        insert_pos = insert_index

    duration_sec = source_range.duration.to_seconds()

    return create_checkpoint(
        db=db,
        timeline_id=timeline_id,
        snapshot=timeline,
        description=f"Added clip '{name}' ({duration_sec:.2f}s) to track '{track.name}'",
        created_by=actor,
        expected_version=expected_version,
        operation_type="add_clip",
        operation_data={
            "track_index": track_index,
            "insert_index": insert_pos,
            "asset_id": str(asset_id),
            "source_range": source_range.model_dump(),
            "name": name,
        },
    )


def remove_clip(
    db: DBSession,
    timeline_id: UUID,
    track_index: int,
    clip_index: int,
    actor: str = "system",
    expected_version: int = 0,
) -> TimelineCheckpointModel:
    current = get_timeline_snapshot(db, timeline_id)
    timeline = deepcopy(current.timeline)
    track = _get_track(timeline, track_index)
    item = _get_item_from_track(track, clip_index)

    if not isinstance(item, Clip):
        raise InvalidOperationError(
            f"Item at index {clip_index} is not a Clip (it's a {type(item).__name__})"
        )

    clip_name = item.name
    track.children.pop(clip_index)

    return create_checkpoint(
        db=db,
        timeline_id=timeline_id,
        snapshot=timeline,
        description=f"Removed clip '{clip_name}' from track '{track.name}'",
        created_by=actor,
        expected_version=expected_version,
        operation_type="remove_clip",
        operation_data={
            "track_index": track_index,
            "clip_index": clip_index,
            "clip_name": clip_name,
        },
    )


def trim_clip(
    db: DBSession,
    timeline_id: UUID,
    track_index: int,
    clip_index: int,
    new_source_range: TimeRange,
    actor: str = "system",
    expected_version: int = 0,
) -> TimelineCheckpointModel:
    current = get_timeline_snapshot(db, timeline_id)
    timeline = deepcopy(current.timeline)
    track = _get_track(timeline, track_index)
    item = _get_item_from_track(track, clip_index)

    if not isinstance(item, Clip):
        raise InvalidOperationError(f"Item at index {clip_index} is not a Clip")

    old_duration = item.source_range.duration.to_seconds()
    new_duration = new_source_range.duration.to_seconds()
    item.source_range = new_source_range

    return create_checkpoint(
        db=db,
        timeline_id=timeline_id,
        snapshot=timeline,
        description=f"Trimmed clip '{item.name}' ({old_duration:.2f}s → {new_duration:.2f}s)",
        created_by=actor,
        expected_version=expected_version,
        operation_type="trim_clip",
        operation_data={
            "track_index": track_index,
            "clip_index": clip_index,
            "old_source_range": {"duration_sec": old_duration},
            "new_source_range": new_source_range.model_dump(),
        },
    )


def slip_clip(
    db: DBSession,
    timeline_id: UUID,
    track_index: int,
    clip_index: int,
    offset: RationalTime,
    actor: str = "system",
    expected_version: int = 0,
) -> TimelineCheckpointModel:
    current = get_timeline_snapshot(db, timeline_id)
    timeline = deepcopy(current.timeline)
    track = _get_track(timeline, track_index)
    item = _get_item_from_track(track, clip_index)

    if not isinstance(item, Clip):
        raise InvalidOperationError(f"Item at index {clip_index} is not a Clip")

    old_start = item.source_range.start_time
    new_start = old_start + offset

    item.source_range = TimeRange(
        start_time=new_start,
        duration=item.source_range.duration,
    )

    offset_frames = offset.value
    direction = "forward" if offset_frames > 0 else "backward"

    return create_checkpoint(
        db=db,
        timeline_id=timeline_id,
        snapshot=timeline,
        description=f"Slipped clip '{item.name}' {abs(offset_frames):.0f} frames {direction}",
        created_by=actor,
        expected_version=expected_version,
        operation_type="slip_clip",
        operation_data={
            "track_index": track_index,
            "clip_index": clip_index,
            "offset": offset.model_dump(),
        },
    )


def move_clip(
    db: DBSession,
    timeline_id: UUID,
    from_track: int,
    from_index: int,
    to_track: int,
    to_index: int,
    actor: str = "system",
    expected_version: int = 0,
) -> TimelineCheckpointModel:
    current = get_timeline_snapshot(db, timeline_id)
    timeline = deepcopy(current.timeline)
    src_track = _get_track(timeline, from_track)
    dst_track = _get_track(timeline, to_track)
    item = _get_item_from_track(src_track, from_index)

    if not isinstance(item, Clip):
        raise InvalidOperationError(f"Item at index {from_index} is not a Clip")

    src_track.children.pop(from_index)

    if from_track == to_track and to_index > from_index:
        to_index -= 1

    to_index = max(0, min(to_index, len(dst_track.children)))
    dst_track.children.insert(to_index, item)

    if from_track == to_track:
        desc = f"Moved clip '{item.name}' from position {from_index} to {to_index} in track '{src_track.name}'"
    else:
        desc = f"Moved clip '{item.name}' from track '{src_track.name}' to track '{dst_track.name}'"

    return create_checkpoint(
        db=db,
        timeline_id=timeline_id,
        snapshot=timeline,
        description=desc,
        created_by=actor,
        expected_version=expected_version,
        operation_type="move_clip",
        operation_data={
            "from_track": from_track,
            "from_index": from_index,
            "to_track": to_track,
            "to_index": to_index,
            "clip_name": item.name,
        },
    )


def replace_clip_media(
    db: DBSession,
    timeline_id: UUID,
    track_index: int,
    clip_index: int,
    new_asset_id: UUID,
    actor: str = "system",
    expected_version: int = 0,
) -> TimelineCheckpointModel:
    current = get_timeline_snapshot(db, timeline_id)
    timeline = deepcopy(current.timeline)
    track = _get_track(timeline, track_index)
    item = _get_item_from_track(track, clip_index)

    if not isinstance(item, Clip):
        raise InvalidOperationError(f"Item at index {clip_index} is not a Clip")

    old_ref = item.media_reference
    old_asset_id = old_ref.asset_id if isinstance(old_ref, ExternalReference) else None
    item.media_reference = ExternalReference(asset_id=new_asset_id)

    return create_checkpoint(
        db=db,
        timeline_id=timeline_id,
        snapshot=timeline,
        description=f"Replaced media for clip '{item.name}'",
        created_by=actor,
        expected_version=expected_version,
        operation_type="replace_clip_media",
        operation_data={
            "track_index": track_index,
            "clip_index": clip_index,
            "old_asset_id": str(old_asset_id) if old_asset_id else None,
            "new_asset_id": str(new_asset_id),
        },
    )


def add_gap(
    db: DBSession,
    timeline_id: UUID,
    track_index: int,
    duration: RationalTime,
    insert_index: int | None = None,
    name: str = "",
    actor: str = "system",
    expected_version: int = 0,
) -> TimelineCheckpointModel:
    current = get_timeline_snapshot(db, timeline_id)
    timeline = deepcopy(current.timeline)
    track = _get_track(timeline, track_index)
    gap = Gap.with_duration(duration, name=name)

    if insert_index is None or insert_index >= len(track.children):
        track.children.append(gap)
        insert_pos = len(track.children) - 1
    else:
        insert_index = max(0, insert_index)
        track.children.insert(insert_index, gap)
        insert_pos = insert_index

    duration_sec = duration.to_seconds()

    return create_checkpoint(
        db=db,
        timeline_id=timeline_id,
        snapshot=timeline,
        description=f"Added {duration_sec:.2f}s gap to track '{track.name}'",
        created_by=actor,
        expected_version=expected_version,
        operation_type="add_gap",
        operation_data={
            "track_index": track_index,
            "insert_index": insert_pos,
            "duration": duration.model_dump(),
        },
    )


def remove_gap(
    db: DBSession,
    timeline_id: UUID,
    track_index: int,
    gap_index: int,
    actor: str = "system",
    expected_version: int = 0,
) -> TimelineCheckpointModel:
    current = get_timeline_snapshot(db, timeline_id)
    timeline = deepcopy(current.timeline)
    track = _get_track(timeline, track_index)
    item = _get_item_from_track(track, gap_index)

    if not isinstance(item, Gap):
        raise InvalidOperationError(
            f"Item at index {gap_index} is not a Gap (it's a {type(item).__name__})"
        )

    duration_sec = item.source_range.duration.to_seconds()
    track.children.pop(gap_index)

    return create_checkpoint(
        db=db,
        timeline_id=timeline_id,
        snapshot=timeline,
        description=f"Removed {duration_sec:.2f}s gap from track '{track.name}'",
        created_by=actor,
        expected_version=expected_version,
        operation_type="remove_gap",
        operation_data={
            "track_index": track_index,
            "gap_index": gap_index,
        },
    )


def adjust_gap_duration(
    db: DBSession,
    timeline_id: UUID,
    track_index: int,
    gap_index: int,
    new_duration: RationalTime,
    actor: str = "system",
    expected_version: int = 0,
) -> TimelineCheckpointModel:
    current = get_timeline_snapshot(db, timeline_id)
    timeline = deepcopy(current.timeline)
    track = _get_track(timeline, track_index)
    item = _get_item_from_track(track, gap_index)

    if not isinstance(item, Gap):
        raise InvalidOperationError(f"Item at index {gap_index} is not a Gap")

    old_duration = item.source_range.duration.to_seconds()
    new_duration_sec = new_duration.to_seconds()

    item.source_range = TimeRange(
        start_time=RationalTime(value=0, rate=new_duration.rate),
        duration=new_duration,
    )

    return create_checkpoint(
        db=db,
        timeline_id=timeline_id,
        snapshot=timeline,
        description=f"Adjusted gap duration ({old_duration:.2f}s → {new_duration_sec:.2f}s)",
        created_by=actor,
        expected_version=expected_version,
        operation_type="adjust_gap_duration",
        operation_data={
            "track_index": track_index,
            "gap_index": gap_index,
            "old_duration_sec": old_duration,
            "new_duration": new_duration.model_dump(),
        },
    )


def add_transition(
    db: DBSession,
    timeline_id: UUID,
    track_index: int,
    position: int,
    transition_type: TransitionType = TransitionType.SMPTE_DISSOLVE,
    in_offset: RationalTime | None = None,
    out_offset: RationalTime | None = None,
    actor: str = "system",
    expected_version: int = 0,
) -> TimelineCheckpointModel:
    current = get_timeline_snapshot(db, timeline_id)
    timeline = deepcopy(current.timeline)
    track = _get_track(timeline, track_index)
    rate = timeline.metadata.get("default_rate", 24.0)

    if in_offset is None:
        in_offset = RationalTime(value=12, rate=rate)
    if out_offset is None:
        out_offset = RationalTime(value=12, rate=rate)

    _validate_transition_position(track, position)

    transition = Transition(
        transition_type=transition_type,
        in_offset=in_offset,
        out_offset=out_offset,
    )

    track.children.insert(position, transition)

    duration_frames = in_offset.value + out_offset.value

    return create_checkpoint(
        db=db,
        timeline_id=timeline_id,
        snapshot=timeline,
        description=f"Added {transition_type.value} transition ({duration_frames:.0f} frames) in track '{track.name}'",
        created_by=actor,
        expected_version=expected_version,
        operation_type="add_transition",
        operation_data={
            "track_index": track_index,
            "position": position,
            "transition_type": transition_type.value,
            "in_offset": in_offset.model_dump(),
            "out_offset": out_offset.model_dump(),
        },
    )


def remove_transition(
    db: DBSession,
    timeline_id: UUID,
    track_index: int,
    transition_index: int,
    actor: str = "system",
    expected_version: int = 0,
) -> TimelineCheckpointModel:
    current = get_timeline_snapshot(db, timeline_id)
    timeline = deepcopy(current.timeline)
    track = _get_track(timeline, track_index)
    item = _get_item_from_track(track, transition_index)

    if not isinstance(item, Transition):
        raise InvalidOperationError(
            f"Item at index {transition_index} is not a Transition"
        )

    track.children.pop(transition_index)

    return create_checkpoint(
        db=db,
        timeline_id=timeline_id,
        snapshot=timeline,
        description=f"Removed transition from track '{track.name}'",
        created_by=actor,
        expected_version=expected_version,
        operation_type="remove_transition",
        operation_data={
            "track_index": track_index,
            "transition_index": transition_index,
        },
    )


def modify_transition(
    db: DBSession,
    timeline_id: UUID,
    track_index: int,
    transition_index: int,
    transition_type: TransitionType | None = None,
    in_offset: RationalTime | None = None,
    out_offset: RationalTime | None = None,
    actor: str = "system",
    expected_version: int = 0,
) -> TimelineCheckpointModel:
    current = get_timeline_snapshot(db, timeline_id)
    timeline = deepcopy(current.timeline)
    track = _get_track(timeline, track_index)
    item = _get_item_from_track(track, transition_index)

    if not isinstance(item, Transition):
        raise InvalidOperationError(
            f"Item at index {transition_index} is not a Transition"
        )

    changes = []

    if transition_type is not None:
        item.transition_type = transition_type
        changes.append(f"type={transition_type.value}")
    if in_offset is not None:
        item.in_offset = in_offset
        changes.append(f"in_offset={in_offset.value:.0f}f")
    if out_offset is not None:
        item.out_offset = out_offset
        changes.append(f"out_offset={out_offset.value:.0f}f")
    return create_checkpoint(
        db=db,
        timeline_id=timeline_id,
        snapshot=timeline,
        description=f"Modified transition: {', '.join(changes)}",
        created_by=actor,
        expected_version=expected_version,
        operation_type="modify_transition",
        operation_data={
            "track_index": track_index,
            "transition_index": transition_index,
            "transition_type": transition_type.value if transition_type else None,
            "in_offset": in_offset.model_dump() if in_offset else None,
            "out_offset": out_offset.model_dump() if out_offset else None,
        },
    )


def nest_clips_as_stack(
    db: DBSession,
    timeline_id: UUID,
    track_index: int,
    start_index: int,
    end_index: int,
    stack_name: str,
    actor: str = "system",
    expected_version: int = 0,
) -> TimelineCheckpointModel:
    current = get_timeline_snapshot(db, timeline_id)
    timeline = deepcopy(current.timeline)
    track = _get_track(timeline, track_index)

    if start_index < 0 or end_index >= len(track.children) or start_index > end_index:
        raise InvalidOperationError(
            f"Invalid range [{start_index}:{end_index}] for track with "
            f"{len(track.children)} items"
        )

    items_to_nest = track.children[start_index : end_index + 1]

    inner_track = Track(
        name=f"{stack_name}_track",
        kind=track.kind,
        children=items_to_nest,
    )

    nested_stack = Stack(
        name=stack_name,
        children=[inner_track],
    )
    track.children = (
        track.children[:start_index] + [nested_stack] + track.children[end_index + 1 :]
    )
    num_items = end_index - start_index + 1
    return create_checkpoint(
        db=db,
        timeline_id=timeline_id,
        snapshot=timeline,
        description=f"Nested {num_items} items as '{stack_name}' in track '{track.name}'",
        created_by=actor,
        expected_version=expected_version,
        operation_type="nest_clips_as_stack",
        operation_data={
            "track_index": track_index,
            "start_index": start_index,
            "end_index": end_index,
            "stack_name": stack_name,
            "num_items": num_items,
        },
    )


def flatten_nested_stack(
    db: DBSession,
    timeline_id: UUID,
    track_index: int,
    stack_index: int,
    actor: str = "system",
    expected_version: int = 0,
) -> TimelineCheckpointModel:
    current = get_timeline_snapshot(db, timeline_id)
    timeline = deepcopy(current.timeline)
    track = _get_track(timeline, track_index)
    item = _get_item_from_track(track, stack_index)

    if not isinstance(item, Stack):
        raise InvalidOperationError(f"Item at index {stack_index} is not a Stack")

    stack_name = item.name

    if not item.children:
        raise InvalidOperationError("Stack has no children to flatten")

    first_child = item.children[0]

    if isinstance(first_child, Track):
        items_to_inline = first_child.children
    elif isinstance(first_child, Stack):
        items_to_inline = [first_child]
    else:
        items_to_inline = []

    track.children = (
        track.children[:stack_index]
        + list(items_to_inline)
        + track.children[stack_index + 1 :]
    )
    return create_checkpoint(
        db=db,
        timeline_id=timeline_id,
        snapshot=timeline,
        description=f"Flattened nested stack '{stack_name}' ({len(items_to_inline)} items)",
        created_by=actor,
        expected_version=expected_version,
        operation_type="flatten_nested_stack",
        operation_data={
            "track_index": track_index,
            "stack_index": stack_index,
            "stack_name": stack_name,
            "num_items_inlined": len(items_to_inline),
        },
    )


def add_marker(
    db: DBSession,
    timeline_id: UUID,
    track_index: int,
    item_index: int,
    marked_range: TimeRange,
    name: str = "",
    color: MarkerColor = MarkerColor.RED,
    metadata: dict[str, Any] | None = None,
    actor: str = "system",
    expected_version: int = 0,
) -> TimelineCheckpointModel:
    current = get_timeline_snapshot(db, timeline_id)
    timeline = deepcopy(current.timeline)
    track = _get_track(timeline, track_index)
    item = _get_item_from_track(track, item_index)

    if not hasattr(item, "markers"):
        raise InvalidOperationError(
            f"Item type {type(item).__name__} does not support markers"
        )

    marker = Marker(
        name=name,
        marked_range=marked_range,
        color=color,
        metadata=metadata or {},
    )

    item.markers.append(marker)
    item_name = getattr(item, "name", f"item[{item_index}]")

    return create_checkpoint(
        db=db,
        timeline_id=timeline_id,
        snapshot=timeline,
        description=f"Added marker '{name}' to '{item_name}'",
        created_by=actor,
        expected_version=expected_version,
        operation_type="add_marker",
        operation_data={
            "track_index": track_index,
            "item_index": item_index,
            "marker": marker.model_dump(),
        },
    )


def remove_marker(
    db: DBSession,
    timeline_id: UUID,
    track_index: int,
    item_index: int,
    marker_index: int,
    actor: str = "system",
    expected_version: int = 0,
) -> TimelineCheckpointModel:
    current = get_timeline_snapshot(db, timeline_id)
    timeline = deepcopy(current.timeline)
    track = _get_track(timeline, track_index)
    item = _get_item_from_track(track, item_index)

    if not hasattr(item, "markers"):
        raise InvalidOperationError(
            f"Item type {type(item).__name__} does not support markers"
        )

    if marker_index < 0 or marker_index >= len(item.markers):
        raise InvalidOperationError(f"Marker index {marker_index} out of range")

    marker = item.markers.pop(marker_index)
    item_name = getattr(item, "name", f"item[{item_index}]")

    return create_checkpoint(
        db=db,
        timeline_id=timeline_id,
        snapshot=timeline,
        description=f"Removed marker '{marker.name}' from '{item_name}'",
        created_by=actor,
        expected_version=expected_version,
        operation_type="remove_marker",
        operation_data={
            "track_index": track_index,
            "item_index": item_index,
            "marker_index": marker_index,
        },
    )


def add_effect(
    db: DBSession,
    timeline_id: UUID,
    track_index: int,
    item_index: int,
    effect: EffectType,
    actor: str = "system",
    expected_version: int = 0,
) -> TimelineCheckpointModel:
    current = get_timeline_snapshot(db, timeline_id)
    timeline = deepcopy(current.timeline)
    track = _get_track(timeline, track_index)
    item = _get_item_from_track(track, item_index)

    if not hasattr(item, "effects"):
        raise InvalidOperationError(
            f"Item type {type(item).__name__} does not support effects"
        )

    item.effects.append(effect)
    item_name = getattr(item, "name", f"item[{item_index}]")
    effect_name = getattr(effect, "effect_name", type(effect).__name__)

    return create_checkpoint(
        db=db,
        timeline_id=timeline_id,
        snapshot=timeline,
        description=f"Added {effect_name} effect to '{item_name}'",
        created_by=actor,
        expected_version=expected_version,
        operation_type="add_effect",
        operation_data={
            "track_index": track_index,
            "item_index": item_index,
            "effect": effect.model_dump(),
        },
    )


def remove_effect(
    db: DBSession,
    timeline_id: UUID,
    track_index: int,
    item_index: int,
    effect_index: int,
    actor: str = "system",
    expected_version: int = 0,
) -> TimelineCheckpointModel:
    current = get_timeline_snapshot(db, timeline_id)
    timeline = deepcopy(current.timeline)
    track = _get_track(timeline, track_index)
    item = _get_item_from_track(track, item_index)

    if not hasattr(item, "effects"):
        raise InvalidOperationError(
            f"Item type {type(item).__name__} does not support effects"
        )

    if effect_index < 0 or effect_index >= len(item.effects):
        raise InvalidOperationError(f"Effect index {effect_index} out of range")

    effect = item.effects.pop(effect_index)
    item_name = getattr(item, "name", f"item[{item_index}]")
    effect_name = getattr(effect, "effect_name", type(effect).__name__)

    return create_checkpoint(
        db=db,
        timeline_id=timeline_id,
        snapshot=timeline,
        description=f"Removed {effect_name} effect from '{item_name}'",
        created_by=actor,
        expected_version=expected_version,
        operation_type="remove_effect",
        operation_data={
            "track_index": track_index,
            "item_index": item_index,
            "effect_index": effect_index,
        },
    )


def replace_timeline(
    db: DBSession,
    timeline_id: UUID,
    new_snapshot: Timeline,
    description: str,
    actor: str = "system",
    expected_version: int = 0,
) -> TimelineCheckpointModel:
    return create_checkpoint(
        db=db,
        timeline_id=timeline_id,
        snapshot=new_snapshot,
        description=description,
        created_by=actor,
        expected_version=expected_version,
        operation_type="replace_timeline",
        operation_data={
            "description": description,
        },
    )


def clear_track(
    db: DBSession,
    timeline_id: UUID,
    track_index: int,
    actor: str = "system",
    expected_version: int = 0,
) -> TimelineCheckpointModel:
    current = get_timeline_snapshot(db, timeline_id)
    timeline = deepcopy(current.timeline)
    track = _get_track(timeline, track_index)
    num_items = len(track.children)
    track_name = track.name
    track.children = []

    return create_checkpoint(
        db=db,
        timeline_id=timeline_id,
        snapshot=timeline,
        description=f"Cleared track '{track_name}' ({num_items} items removed)",
        created_by=actor,
        expected_version=expected_version,
        operation_type="clear_track",
        operation_data={
            "track_index": track_index,
            "track_name": track_name,
            "num_items_removed": num_items,
        },
    )
