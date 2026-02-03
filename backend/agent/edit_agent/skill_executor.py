from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from models.timeline_models import (
    Effect,
    FreezeFrame,
    LinearTimeWarp,
    RationalTime,
    TimeRange,
    TransitionType,
)
from operators import timeline_editor
from operators.timeline_operator import get_timeline_snapshot

from .types import EditOperation


class SkillExecutionError(Exception):
    pass


@dataclass
class SkillExecutionResult:
    description: str
    operations: list[EditOperation]
    new_version: int | None
    warnings: list[str]


def execute_skill(
    skill_id: str,
    arguments: dict[str, Any],
    db: Session,
    timeline_id: UUID,
    actor: str,
    apply: bool = True,
) -> SkillExecutionResult:
    current = get_timeline_snapshot(db, timeline_id)
    timeline = current.timeline
    expected_version = current.version
    rate = _get_default_rate(timeline.metadata)

    operations: list[EditOperation] = []
    warnings: list[str] = []
    description = f"Executed {skill_id}"

    def _apply_checkpoint(checkpoint):
        nonlocal expected_version
        if checkpoint is not None:
            expected_version = checkpoint.version

    if skill_id == "cuts.trim":
        track_index = arguments["track_index"]
        clip_index = arguments["clip_index"]
        start_ms = arguments["start_ms"]
        end_ms = arguments["end_ms"]
        new_range = _time_range_from_ms(start_ms, end_ms, rate)
        operations.append(
            EditOperation(
                operation_type="trim_clip",
                operation_data={
                    "track_index": track_index,
                    "clip_index": clip_index,
                    "new_source_range": new_range.model_dump(),
                },
            )
        )
        if apply:
            checkpoint = timeline_editor.trim_clip(
                db,
                timeline_id,
                track_index,
                clip_index,
                new_range,
                actor=actor,
                expected_version=expected_version,
            )
            _apply_checkpoint(checkpoint)
        description = "Trimmed clip range"

    elif skill_id == "cuts.split":
        track_index = arguments["track_index"]
        clip_index = arguments["clip_index"]
        split_ms = arguments["split_ms"]
        split_offset = RationalTime.from_milliseconds(split_ms, rate)
        operations.append(
            EditOperation(
                operation_type="split_clip",
                operation_data={
                    "track_index": track_index,
                    "clip_index": clip_index,
                    "split_offset": split_offset.model_dump(),
                },
            )
        )
        if apply:
            checkpoint = timeline_editor.split_clip(
                db,
                timeline_id,
                track_index,
                clip_index,
                split_offset,
                actor=actor,
                expected_version=expected_version,
            )
            _apply_checkpoint(checkpoint)
        description = "Split clip"

    elif skill_id == "cuts.insert":
        track_index = arguments["track_index"]
        asset_id = UUID(arguments["asset_id"])
        start_ms = arguments["source_start_ms"]
        end_ms = arguments["source_end_ms"]
        insert_index = arguments.get("insert_index")
        name = arguments.get("name")
        source_range = _time_range_from_ms(start_ms, end_ms, rate)
        operations.append(
            EditOperation(
                operation_type="add_clip",
                operation_data={
                    "track_index": track_index,
                    "insert_index": insert_index,
                    "asset_id": str(asset_id),
                    "source_range": source_range.model_dump(),
                    "name": name,
                },
            )
        )
        if apply:
            checkpoint = timeline_editor.add_clip(
                db,
                timeline_id,
                track_index,
                asset_id,
                source_range,
                insert_index=insert_index,
                name=name,
                actor=actor,
                expected_version=expected_version,
            )
            _apply_checkpoint(checkpoint)
        description = "Inserted clip"

    elif skill_id == "cuts.overwrite":
        track_index = arguments["track_index"]
        clip_index = arguments["clip_index"]
        asset_id = UUID(arguments["asset_id"])
        start_ms = arguments["source_start_ms"]
        end_ms = arguments["source_end_ms"]
        source_range = _time_range_from_ms(start_ms, end_ms, rate)
        operations.extend(
            [
                EditOperation(
                    operation_type="replace_clip_media",
                    operation_data={
                        "track_index": track_index,
                        "clip_index": clip_index,
                        "new_asset_id": str(asset_id),
                    },
                ),
                EditOperation(
                    operation_type="trim_clip",
                    operation_data={
                        "track_index": track_index,
                        "clip_index": clip_index,
                        "new_source_range": source_range.model_dump(),
                    },
                ),
            ]
        )
        if apply:
            checkpoint = timeline_editor.replace_clip_media(
                db,
                timeline_id,
                track_index,
                clip_index,
                asset_id,
                actor=actor,
                expected_version=expected_version,
            )
            _apply_checkpoint(checkpoint)
            checkpoint = timeline_editor.trim_clip(
                db,
                timeline_id,
                track_index,
                clip_index,
                source_range,
                actor=actor,
                expected_version=expected_version,
            )
            _apply_checkpoint(checkpoint)
        description = "Overwrote clip media"

    elif skill_id == "cuts.move":
        from_track = arguments["from_track"]
        from_index = arguments["from_index"]
        to_track = arguments["to_track"]
        to_index = arguments["to_index"]
        operations.append(
            EditOperation(
                operation_type="move_clip",
                operation_data={
                    "from_track": from_track,
                    "from_index": from_index,
                    "to_track": to_track,
                    "to_index": to_index,
                },
            )
        )
        if apply:
            checkpoint = timeline_editor.move_clip(
                db,
                timeline_id,
                from_track,
                from_index,
                to_track,
                to_index,
                actor=actor,
                expected_version=expected_version,
            )
            _apply_checkpoint(checkpoint)
        description = "Moved clip"

    elif skill_id == "cuts.slip":
        track_index = arguments["track_index"]
        clip_index = arguments["clip_index"]
        offset_ms = arguments["offset_ms"]
        offset = RationalTime.from_milliseconds(offset_ms, rate)
        operations.append(
            EditOperation(
                operation_type="slip_clip",
                operation_data={
                    "track_index": track_index,
                    "clip_index": clip_index,
                    "offset": offset.model_dump(),
                },
            )
        )
        if apply:
            checkpoint = timeline_editor.slip_clip(
                db,
                timeline_id,
                track_index,
                clip_index,
                offset,
                actor=actor,
                expected_version=expected_version,
            )
            _apply_checkpoint(checkpoint)
        description = "Slipped clip"

    elif skill_id == "cuts.slide":
        track_index = arguments["track_index"]
        clip_index = arguments["clip_index"]
        to_index = arguments["to_index"]
        operations.append(
            EditOperation(
                operation_type="move_clip",
                operation_data={
                    "from_track": track_index,
                    "from_index": clip_index,
                    "to_track": track_index,
                    "to_index": to_index,
                },
            )
        )
        if apply:
            checkpoint = timeline_editor.move_clip(
                db,
                timeline_id,
                track_index,
                clip_index,
                track_index,
                to_index,
                actor=actor,
                expected_version=expected_version,
            )
            _apply_checkpoint(checkpoint)
        description = "Slid clip"

    elif skill_id == "cuts.pacing":
        track_index = arguments["track_index"]
        gap_index = arguments["gap_index"]
        duration_ms = arguments["duration_ms"]
        new_duration = RationalTime.from_milliseconds(duration_ms, rate)
        operations.append(
            EditOperation(
                operation_type="adjust_gap_duration",
                operation_data={
                    "track_index": track_index,
                    "gap_index": gap_index,
                    "new_duration": new_duration.model_dump(),
                },
            )
        )
        if apply:
            checkpoint = timeline_editor.adjust_gap_duration(
                db,
                timeline_id,
                track_index,
                gap_index,
                new_duration,
                actor=actor,
                expected_version=expected_version,
            )
            _apply_checkpoint(checkpoint)
        description = "Adjusted pacing gap"

    elif skill_id == "silences.remove":
        track_index = arguments["track_index"]
        clip_index = arguments["clip_index"]
        segments = arguments["segments"]
        description = "Removed silent ranges"
        operations.extend(
            _build_silence_operations(track_index, clip_index, segments, rate)
        )
        if apply:
            for op in operations:
                expected_version = _apply_operation(
                    db, timeline_id, op, actor, expected_version
                )

    elif skill_id == "brolls.add":
        track_index = arguments.get("track_index")
        asset_id = UUID(arguments["asset_id"])
        start_ms = arguments["source_start_ms"]
        end_ms = arguments["source_end_ms"]
        insert_index = arguments.get("insert_index")
        position = arguments.get("position")
        blur = arguments.get("blur")
        mask = arguments.get("mask")
        name = arguments.get("name")
        source_range = _time_range_from_ms(start_ms, end_ms, rate)

        if track_index is None:
            track_index, expected_version = _ensure_named_track(
                db,
                timeline_id,
                "B-roll",
                actor,
                expected_version,
            )
            current = get_timeline_snapshot(db, timeline_id)
            timeline = current.timeline

        operations.append(
            EditOperation(
                operation_type="add_clip",
                operation_data={
                    "track_index": track_index,
                    "insert_index": insert_index,
                    "asset_id": str(asset_id),
                    "source_range": source_range.model_dump(),
                    "name": name,
                },
            )
        )

        if apply:
            checkpoint = timeline_editor.add_clip(
                db,
                timeline_id,
                track_index,
                asset_id,
                source_range,
                insert_index=insert_index,
                name=name,
                actor=actor,
                expected_version=expected_version,
            )
            _apply_checkpoint(checkpoint)

        effect_ops = []
        if position:
            effect_ops.append(
                _build_effect_operation(
                    track_index,
                    _resolve_insert_index(timeline, track_index, insert_index),
                    "position",
                    position,
                )
            )
        if blur:
            effect_ops.append(
                _build_effect_operation(
                    track_index,
                    _resolve_insert_index(timeline, track_index, insert_index),
                    "blur",
                    {"radius": blur},
                )
            )
        if mask:
            effect_ops.append(
                _build_effect_operation(
                    track_index,
                    _resolve_insert_index(timeline, track_index, insert_index),
                    "mask",
                    mask,
                )
            )
        operations.extend(effect_ops)

        if apply:
            clip_index = _resolve_insert_index(timeline, track_index, insert_index)
            for op in effect_ops:
                expected_version = _apply_operation(
                    db, timeline_id, op, actor, expected_version
                )
        description = "Added b-roll clip"

    elif skill_id == "captions.add":
        captions = arguments["captions"]
        track_index = arguments.get("track_index")
        if track_index is not None:
            snapshot = get_timeline_snapshot(db, timeline_id)
            if track_index >= len(snapshot.timeline.tracks.children):
                track_index = None
            else:
                track_name = getattr(snapshot.timeline.tracks.children[track_index], "name", "")
                if track_name.lower() != "captions":
                    track_index = None
        if track_index is None:
            track_index, expected_version = _ensure_named_track(
                db,
                timeline_id,
                "Captions",
                actor,
                expected_version,
            )
        captions = sorted(captions, key=lambda entry: entry.get("start_ms", 0))
        for entry in captions:
            start_ms = entry["start_ms"]
            end_ms = entry["end_ms"]
            text = entry["text"]
            params = {
                "text": text,
                "font": entry.get("font"),
                "size": entry.get("size"),
                "color": entry.get("color"),
                "bg_color": entry.get("bg_color"),
                "x": entry.get("x"),
                "y": entry.get("y"),
            }
            source_range = _time_range_from_ms(start_ms, end_ms, rate)
            operations.append(
                EditOperation(
                    operation_type="add_generator_clip",
                    operation_data={
                        "track_index": track_index,
                        "generator_kind": "caption",
                        "parameters": params,
                        "source_range": source_range.model_dump(),
                        "name": entry.get("name"),
                    },
                )
            )
            if apply:
                checkpoint = timeline_editor.add_generator_clip(
                    db,
                    timeline_id,
                    track_index,
                    "caption",
                    params,
                    source_range,
                    insert_index=None,
                    name=entry.get("name"),
                    actor=actor,
                    expected_version=expected_version,
                )
                _apply_checkpoint(checkpoint)
        description = "Added captions"

    elif skill_id == "mix.crossfade":
        track_index = arguments["track_index"]
        position = arguments["position"]
        duration_ms = arguments["duration_ms"]
        transition_type = _parse_transition(arguments.get("transition_type"))
        duration_frames = _duration_frames(duration_ms, rate)
        half = RationalTime.from_frames(duration_frames / 2, rate)
        operations.append(
            EditOperation(
                operation_type="add_transition",
                operation_data={
                    "track_index": track_index,
                    "position": position,
                    "transition_type": transition_type.value,
                    "in_offset": half.model_dump(),
                    "out_offset": half.model_dump(),
                },
            )
        )
        if apply:
            checkpoint = timeline_editor.add_transition(
                db,
                timeline_id,
                track_index,
                position,
                transition_type=transition_type,
                in_offset=half,
                out_offset=half,
                actor=actor,
                expected_version=expected_version,
            )
            _apply_checkpoint(checkpoint)
        description = "Added crossfade"

    elif skill_id == "mix.ducking":
        track_index = arguments["track_index"]
        clip_index = arguments["clip_index"]
        segments = arguments.get("segments", [])
        target_db = arguments.get("target_db", -16)
        effect = Effect(
            effect_name="Ducking",
            metadata={
                "type": "ducking",
                "segments": segments,
                "target_db": target_db,
            },
        )
        operations.append(
            EditOperation(
                operation_type="add_effect",
                operation_data={
                    "track_index": track_index,
                    "item_index": clip_index,
                    "effect": effect.model_dump(),
                },
            )
        )
        if apply:
            checkpoint = timeline_editor.add_effect(
                db,
                timeline_id,
                track_index,
                clip_index,
                effect,
                actor=actor,
                expected_version=expected_version,
            )
            _apply_checkpoint(checkpoint)
        description = "Applied ducking"

    elif skill_id == "mix.loudness":
        track_index = arguments["track_index"]
        clip_index = arguments["clip_index"]
        target_lufs = arguments.get("target_lufs", -16)
        lra = arguments.get("lra", 11)
        true_peak = arguments.get("true_peak", -1.5)
        effect = Effect(
            effect_name="Loudness",
            metadata={
                "type": "loudness",
                "target_lufs": target_lufs,
                "lra": lra,
                "true_peak": true_peak,
            },
        )
        operations.append(
            EditOperation(
                operation_type="add_effect",
                operation_data={
                    "track_index": track_index,
                    "item_index": clip_index,
                    "effect": effect.model_dump(),
                },
            )
        )
        if apply:
            checkpoint = timeline_editor.add_effect(
                db,
                timeline_id,
                track_index,
                clip_index,
                effect,
                actor=actor,
                expected_version=expected_version,
            )
            _apply_checkpoint(checkpoint)
        description = "Applied loudness normalization"

    elif skill_id == "colors.lut":
        track_index = arguments["track_index"]
        clip_index = arguments["clip_index"]
        lut_path = arguments["lut_path"]
        intensity = arguments.get("intensity", 1.0)
        effect = Effect(
            effect_name="LUT",
            metadata={
                "type": "lut",
                "path": lut_path,
                "intensity": intensity,
            },
        )
        operations.append(
            EditOperation(
                operation_type="add_effect",
                operation_data={
                    "track_index": track_index,
                    "item_index": clip_index,
                    "effect": effect.model_dump(),
                },
            )
        )
        if apply:
            checkpoint = timeline_editor.add_effect(
                db,
                timeline_id,
                track_index,
                clip_index,
                effect,
                actor=actor,
                expected_version=expected_version,
            )
            _apply_checkpoint(checkpoint)
        description = "Applied LUT"

    elif skill_id == "colors.grade":
        track_index = arguments["track_index"]
        clip_index = arguments["clip_index"]
        effect = Effect(
            effect_name="ColorGrade",
            metadata={
                "type": "grade",
                "brightness": arguments.get("brightness"),
                "contrast": arguments.get("contrast"),
                "saturation": arguments.get("saturation"),
                "gamma": arguments.get("gamma"),
            },
        )
        operations.append(
            EditOperation(
                operation_type="add_effect",
                operation_data={
                    "track_index": track_index,
                    "item_index": clip_index,
                    "effect": effect.model_dump(),
                },
            )
        )
        if apply:
            checkpoint = timeline_editor.add_effect(
                db,
                timeline_id,
                track_index,
                clip_index,
                effect,
                actor=actor,
                expected_version=expected_version,
            )
            _apply_checkpoint(checkpoint)
        description = "Applied color grade"

    elif skill_id == "colors.curves":
        track_index = arguments["track_index"]
        clip_index = arguments["clip_index"]
        effect = Effect(
            effect_name="Curves",
            metadata={
                "type": "curves",
                "preset": arguments.get("preset"),
                "points": arguments.get("points"),
            },
        )
        operations.append(
            EditOperation(
                operation_type="add_effect",
                operation_data={
                    "track_index": track_index,
                    "item_index": clip_index,
                    "effect": effect.model_dump(),
                },
            )
        )
        if apply:
            checkpoint = timeline_editor.add_effect(
                db,
                timeline_id,
                track_index,
                clip_index,
                effect,
                actor=actor,
                expected_version=expected_version,
            )
            _apply_checkpoint(checkpoint)
        description = "Applied curves"

    elif skill_id == "colors.white_balance":
        track_index = arguments["track_index"]
        clip_index = arguments["clip_index"]
        effect = Effect(
            effect_name="WhiteBalance",
            metadata={
                "type": "white_balance",
                "red": arguments.get("red"),
                "green": arguments.get("green"),
                "blue": arguments.get("blue"),
            },
        )
        operations.append(
            EditOperation(
                operation_type="add_effect",
                operation_data={
                    "track_index": track_index,
                    "item_index": clip_index,
                    "effect": effect.model_dump(),
                },
            )
        )
        if apply:
            checkpoint = timeline_editor.add_effect(
                db,
                timeline_id,
                track_index,
                clip_index,
                effect,
                actor=actor,
                expected_version=expected_version,
            )
            _apply_checkpoint(checkpoint)
        description = "Adjusted white balance"

    elif skill_id == "motions.stabilize":
        track_index = arguments["track_index"]
        clip_index = arguments["clip_index"]
        strength = arguments.get("strength", 0.5)
        effect = Effect(
            effect_name="Stabilize",
            metadata={"type": "stabilize", "strength": strength},
        )
        operations.append(
            EditOperation(
                operation_type="add_effect",
                operation_data={
                    "track_index": track_index,
                    "item_index": clip_index,
                    "effect": effect.model_dump(),
                },
            )
        )
        if apply:
            checkpoint = timeline_editor.add_effect(
                db,
                timeline_id,
                track_index,
                clip_index,
                effect,
                actor=actor,
                expected_version=expected_version,
            )
            _apply_checkpoint(checkpoint)
        description = "Applied stabilization"

    elif skill_id == "motions.reframe":
        track_index = arguments["track_index"]
        clip_index = arguments["clip_index"]
        effect = Effect(
            effect_name="Reframe",
            metadata={
                "type": "reframe",
                "x": arguments.get("x"),
                "y": arguments.get("y"),
                "width": arguments.get("width"),
                "height": arguments.get("height"),
            },
        )
        operations.append(
            EditOperation(
                operation_type="add_effect",
                operation_data={
                    "track_index": track_index,
                    "item_index": clip_index,
                    "effect": effect.model_dump(),
                },
            )
        )
        if apply:
            checkpoint = timeline_editor.add_effect(
                db,
                timeline_id,
                track_index,
                clip_index,
                effect,
                actor=actor,
                expected_version=expected_version,
            )
            _apply_checkpoint(checkpoint)
        description = "Applied reframe"

    elif skill_id == "motions.position":
        track_index = arguments["track_index"]
        clip_index = arguments["clip_index"]
        effect = Effect(
            effect_name="Position",
            metadata={
                "type": "position",
                "x": arguments.get("x"),
                "y": arguments.get("y"),
                "width": arguments.get("width"),
                "height": arguments.get("height"),
            },
        )
        operations.append(
            EditOperation(
                operation_type="add_effect",
                operation_data={
                    "track_index": track_index,
                    "item_index": clip_index,
                    "effect": effect.model_dump(),
                },
            )
        )
        if apply:
            checkpoint = timeline_editor.add_effect(
                db,
                timeline_id,
                track_index,
                clip_index,
                effect,
                actor=actor,
                expected_version=expected_version,
            )
            _apply_checkpoint(checkpoint)
        description = "Applied position"

    elif skill_id == "motions.zoom":
        track_index = arguments["track_index"]
        clip_index = arguments["clip_index"]
        effect = Effect(
            effect_name="Zoom",
            metadata={
                "type": "zoom",
                "start_zoom": arguments.get("start_zoom", 1.0),
                "end_zoom": arguments.get("end_zoom", 1.0),
                "center_x": arguments.get("center_x", 0.5),
                "center_y": arguments.get("center_y", 0.5),
            },
        )
        operations.append(
            EditOperation(
                operation_type="add_effect",
                operation_data={
                    "track_index": track_index,
                    "item_index": clip_index,
                    "effect": effect.model_dump(),
                },
            )
        )
        if apply:
            checkpoint = timeline_editor.add_effect(
                db,
                timeline_id,
                track_index,
                clip_index,
                effect,
                actor=actor,
                expected_version=expected_version,
            )
            _apply_checkpoint(checkpoint)
        description = "Applied zoom"

    elif skill_id == "fx.transition":
        track_index = arguments["track_index"]
        position = arguments["position"]
        duration_ms = arguments["duration_ms"]
        transition_type = _parse_transition(arguments.get("transition_type"))
        duration_frames = _duration_frames(duration_ms, rate)
        half = RationalTime.from_frames(duration_frames / 2, rate)
        operations.append(
            EditOperation(
                operation_type="add_transition",
                operation_data={
                    "track_index": track_index,
                    "position": position,
                    "transition_type": transition_type.value,
                    "in_offset": half.model_dump(),
                    "out_offset": half.model_dump(),
                },
            )
        )
        if apply:
            checkpoint = timeline_editor.add_transition(
                db,
                timeline_id,
                track_index,
                position,
                transition_type=transition_type,
                in_offset=half,
                out_offset=half,
                actor=actor,
                expected_version=expected_version,
            )
            _apply_checkpoint(checkpoint)
        description = "Added transition"

    elif skill_id == "fx.speed_ramp":
        track_index = arguments["track_index"]
        clip_index = arguments["clip_index"]
        segments = arguments["segments"]
        description = "Applied speed ramp"
        operations.extend(
            _build_speed_ramp_operations(track_index, clip_index, segments, rate)
        )
        if apply:
            for op in operations:
                expected_version = _apply_operation(
                    db, timeline_id, op, actor, expected_version
                )

    elif skill_id == "fx.freeze_frame":
        track_index = arguments["track_index"]
        clip_index = arguments["clip_index"]
        at_ms = arguments["at_ms"]
        duration_ms = arguments["duration_ms"]
        description = "Inserted freeze frame"
        operations.extend(
            _build_freeze_operations(track_index, clip_index, at_ms, duration_ms, rate)
        )
        if apply:
            for op in operations:
                expected_version = _apply_operation(
                    db, timeline_id, op, actor, expected_version
                )

    elif skill_id == "fx.blur":
        track_index = arguments["track_index"]
        clip_index = arguments["clip_index"]
        radius = arguments.get("radius", 8)
        effect = Effect(
            effect_name="Blur",
            metadata={"type": "blur", "radius": radius},
        )
        operations.append(
            EditOperation(
                operation_type="add_effect",
                operation_data={
                    "track_index": track_index,
                    "item_index": clip_index,
                    "effect": effect.model_dump(),
                },
            )
        )
        if apply:
            checkpoint = timeline_editor.add_effect(
                db,
                timeline_id,
                track_index,
                clip_index,
                effect,
                actor=actor,
                expected_version=expected_version,
            )
            _apply_checkpoint(checkpoint)
        description = "Applied blur"

    elif skill_id == "fx.vignette":
        track_index = arguments["track_index"]
        clip_index = arguments["clip_index"]
        strength = arguments.get("strength", 0.5)
        effect = Effect(
            effect_name="Vignette",
            metadata={"type": "vignette", "strength": strength},
        )
        operations.append(
            EditOperation(
                operation_type="add_effect",
                operation_data={
                    "track_index": track_index,
                    "item_index": clip_index,
                    "effect": effect.model_dump(),
                },
            )
        )
        if apply:
            checkpoint = timeline_editor.add_effect(
                db,
                timeline_id,
                track_index,
                clip_index,
                effect,
                actor=actor,
                expected_version=expected_version,
            )
            _apply_checkpoint(checkpoint)
        description = "Applied vignette"

    elif skill_id == "fx.grain":
        track_index = arguments["track_index"]
        clip_index = arguments["clip_index"]
        amount = arguments.get("amount", 0.2)
        effect = Effect(
            effect_name="Grain",
            metadata={"type": "grain", "amount": amount},
        )
        operations.append(
            EditOperation(
                operation_type="add_effect",
                operation_data={
                    "track_index": track_index,
                    "item_index": clip_index,
                    "effect": effect.model_dump(),
                },
            )
        )
        if apply:
            checkpoint = timeline_editor.add_effect(
                db,
                timeline_id,
                track_index,
                clip_index,
                effect,
                actor=actor,
                expected_version=expected_version,
            )
            _apply_checkpoint(checkpoint)
        description = "Applied grain"

    else:
        raise SkillExecutionError(f"Unknown skill: {skill_id}")

    return SkillExecutionResult(
        description=description,
        operations=operations,
        new_version=expected_version if apply else None,
        warnings=warnings,
    )


def _get_default_rate(metadata: dict[str, Any]) -> float:
    rate = metadata.get("default_rate", 24.0)
    try:
        return float(rate)
    except (TypeError, ValueError):
        return 24.0


def _time_range_from_ms(start_ms: float, end_ms: float, rate: float) -> TimeRange:
    if end_ms <= start_ms:
        raise SkillExecutionError("end_ms must be greater than start_ms")
    return TimeRange.from_milliseconds(start_ms, end_ms - start_ms, rate)


def _duration_frames(duration_ms: float, rate: float) -> float:
    return (duration_ms / 1000.0) * rate


def _parse_transition(value: str | None) -> TransitionType:
    if not value:
        return TransitionType.SMPTE_DISSOLVE
    try:
        return TransitionType(value)
    except ValueError:
        return TransitionType.SMPTE_DISSOLVE


def _ensure_named_track(
    db: Session,
    timeline_id: UUID,
    name: str,
    actor: str,
    expected_version: int,
) -> tuple[int, int]:
    snapshot = get_timeline_snapshot(db, timeline_id)
    for idx, track in enumerate(snapshot.timeline.tracks.children):
        if getattr(track, "name", "").lower() == name.lower():
            return idx, expected_version

    checkpoint = timeline_editor.add_track(
        db,
        timeline_id,
        name=name,
        actor=actor,
        expected_version=expected_version,
    )
    new_snapshot = get_timeline_snapshot(db, timeline_id)
    for idx, track in enumerate(new_snapshot.timeline.tracks.children):
        if getattr(track, "name", "").lower() == name.lower():
            return idx, int(checkpoint.version)

    raise SkillExecutionError(f"Failed to create track '{name}'")


def _resolve_insert_index(timeline, track_index: int, insert_index: int | None) -> int:
    track = timeline.tracks.children[track_index]
    if insert_index is None or insert_index >= len(track.children):
        return len(track.children)
    return max(0, insert_index)


def _build_effect_operation(
    track_index: int,
    clip_index: int,
    effect_type: str,
    params: dict[str, Any],
) -> EditOperation:
    effect = Effect(effect_name=effect_type.title(), metadata={"type": effect_type, **params})
    return EditOperation(
        operation_type="add_effect",
        operation_data={
            "track_index": track_index,
            "item_index": clip_index,
            "effect": effect.model_dump(),
        },
    )


def _build_silence_operations(
    track_index: int,
    clip_index: int,
    segments: list[dict[str, Any]],
    rate: float,
) -> list[EditOperation]:
    ops: list[EditOperation] = []
    for segment in sorted(segments, key=lambda s: s["start_ms"], reverse=True):
        start_ms = segment["start_ms"]
        end_ms = segment["end_ms"]
        if end_ms <= start_ms:
            continue
        end_offset = RationalTime.from_milliseconds(end_ms, rate)
        start_offset = RationalTime.from_milliseconds(start_ms, rate)
        ops.append(
            EditOperation(
                operation_type="split_clip",
                operation_data={
                    "track_index": track_index,
                    "clip_index": clip_index,
                    "split_offset": end_offset.model_dump(),
                },
            )
        )
        ops.append(
            EditOperation(
                operation_type="split_clip",
                operation_data={
                    "track_index": track_index,
                    "clip_index": clip_index,
                    "split_offset": start_offset.model_dump(),
                },
            )
        )
        ops.append(
            EditOperation(
                operation_type="remove_clip",
                operation_data={
                    "track_index": track_index,
                    "clip_index": clip_index + 1,
                },
            )
        )
    return ops


def _build_speed_ramp_operations(
    track_index: int,
    clip_index: int,
    segments: list[dict[str, Any]],
    rate: float,
) -> list[EditOperation]:
    ops: list[EditOperation] = []
    for segment in sorted(segments, key=lambda s: s["start_ms"], reverse=True):
        start_ms = segment["start_ms"]
        end_ms = segment["end_ms"]
        speed = segment.get("speed", 1.0)
        end_offset = RationalTime.from_milliseconds(end_ms, rate)
        start_offset = RationalTime.from_milliseconds(start_ms, rate)
        ops.append(
            EditOperation(
                operation_type="split_clip",
                operation_data={
                    "track_index": track_index,
                    "clip_index": clip_index,
                    "split_offset": end_offset.model_dump(),
                },
            )
        )
        ops.append(
            EditOperation(
                operation_type="split_clip",
                operation_data={
                    "track_index": track_index,
                    "clip_index": clip_index,
                    "split_offset": start_offset.model_dump(),
                },
            )
        )
        effect = LinearTimeWarp(time_scalar=speed)
        ops.append(
            EditOperation(
                operation_type="add_effect",
                operation_data={
                    "track_index": track_index,
                    "item_index": clip_index + 1,
                    "effect": effect.model_dump(),
                },
            )
        )
    return ops


def _build_freeze_operations(
    track_index: int,
    clip_index: int,
    at_ms: float,
    duration_ms: float,
    rate: float,
) -> list[EditOperation]:
    ops: list[EditOperation] = []
    start_offset = RationalTime.from_milliseconds(at_ms, rate)
    end_offset = RationalTime.from_milliseconds(at_ms + duration_ms, rate)
    ops.append(
        EditOperation(
            operation_type="split_clip",
            operation_data={
                "track_index": track_index,
                "clip_index": clip_index,
                "split_offset": end_offset.model_dump(),
            },
        )
    )
    ops.append(
        EditOperation(
            operation_type="split_clip",
            operation_data={
                "track_index": track_index,
                "clip_index": clip_index,
                "split_offset": start_offset.model_dump(),
            },
        )
    )
    effect = FreezeFrame()
    ops.append(
        EditOperation(
            operation_type="add_effect",
            operation_data={
                "track_index": track_index,
                "item_index": clip_index + 1,
                "effect": effect.model_dump(),
            },
        )
    )
    return ops


def _apply_operation(
    db: Session,
    timeline_id: UUID,
    operation: EditOperation,
    actor: str,
    expected_version: int,
) -> int:
    op_type = operation.operation_type
    data = operation.operation_data

    if op_type == "trim_clip":
        new_range = TimeRange.model_validate(data["new_source_range"])
        checkpoint = timeline_editor.trim_clip(
            db,
            timeline_id,
            data["track_index"],
            data["clip_index"],
            new_range,
            actor=actor,
            expected_version=expected_version,
        )
    elif op_type == "split_clip":
        split_offset = RationalTime.model_validate(data["split_offset"])
        checkpoint = timeline_editor.split_clip(
            db,
            timeline_id,
            data["track_index"],
            data["clip_index"],
            split_offset,
            actor=actor,
            expected_version=expected_version,
        )
    elif op_type == "remove_clip":
        checkpoint = timeline_editor.remove_clip(
            db,
            timeline_id,
            data["track_index"],
            data["clip_index"],
            actor=actor,
            expected_version=expected_version,
        )
    elif op_type == "add_clip":
        source_range = TimeRange.model_validate(data["source_range"])
        checkpoint = timeline_editor.add_clip(
            db,
            timeline_id,
            data["track_index"],
            UUID(data["asset_id"]),
            source_range,
            insert_index=data.get("insert_index"),
            name=data.get("name"),
            actor=actor,
            expected_version=expected_version,
        )
    elif op_type == "replace_clip_media":
        checkpoint = timeline_editor.replace_clip_media(
            db,
            timeline_id,
            data["track_index"],
            data["clip_index"],
            UUID(data["new_asset_id"]),
            actor=actor,
            expected_version=expected_version,
        )
    elif op_type == "move_clip":
        checkpoint = timeline_editor.move_clip(
            db,
            timeline_id,
            data["from_track"],
            data["from_index"],
            data["to_track"],
            data["to_index"],
            actor=actor,
            expected_version=expected_version,
        )
    elif op_type == "slip_clip":
        offset = RationalTime.model_validate(data["offset"])
        checkpoint = timeline_editor.slip_clip(
            db,
            timeline_id,
            data["track_index"],
            data["clip_index"],
            offset,
            actor=actor,
            expected_version=expected_version,
        )
    elif op_type == "add_transition":
        checkpoint = timeline_editor.add_transition(
            db,
            timeline_id,
            data["track_index"],
            data["position"],
            transition_type=_parse_transition(data.get("transition_type")),
            in_offset=RationalTime.model_validate(data["in_offset"]),
            out_offset=RationalTime.model_validate(data["out_offset"]),
            actor=actor,
            expected_version=expected_version,
        )
    elif op_type == "add_effect":
        effect_data = data["effect"]
        schema = effect_data.get("OTIO_SCHEMA")
        if schema == "LinearTimeWarp.1":
            effect = LinearTimeWarp.model_validate(effect_data)
        elif schema == "FreezeFrame.1":
            effect = FreezeFrame.model_validate(effect_data)
        else:
            effect = Effect.model_validate(effect_data)
        checkpoint = timeline_editor.add_effect(
            db,
            timeline_id,
            data["track_index"],
            data["item_index"],
            effect,
            actor=actor,
            expected_version=expected_version,
        )
    elif op_type == "add_generator_clip":
        source_range = TimeRange.model_validate(data["source_range"])
        checkpoint = timeline_editor.add_generator_clip(
            db,
            timeline_id,
            data["track_index"],
            data["generator_kind"],
            data.get("parameters", {}),
            source_range,
            insert_index=data.get("insert_index"),
            name=data.get("name"),
            actor=actor,
            expected_version=expected_version,
        )
    elif op_type == "adjust_gap_duration":
        new_duration = RationalTime.model_validate(data["new_duration"])
        checkpoint = timeline_editor.adjust_gap_duration(
            db,
            timeline_id,
            data["track_index"],
            data["gap_index"],
            new_duration,
            actor=actor,
            expected_version=expected_version,
        )
    else:
        raise SkillExecutionError(f"Unsupported operation: {op_type}")

    return int(checkpoint.version)
