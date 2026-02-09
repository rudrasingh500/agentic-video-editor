#!/usr/bin/env python3
import json
import logging
import math
import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from google.cloud import storage
from google.oauth2 import service_account

from graphics_generator import OverlayGenerator, OverlayAsset



logger = logging.getLogger("ffmpeg-renderer")


class RenderError(Exception):
    pass


@dataclass
class RenderManifest:
    job_id: str
    project_id: str
    timeline_version: int
    timeline_snapshot: dict[str, Any]
    asset_map: dict[str, str]
    preset: dict[str, Any]
    input_bucket: str
    output_bucket: str
    output_path: str
    start_frame: int | None = None
    end_frame: int | None = None
    callback_url: str | None = None


@dataclass
class InputSpec:
    path: str
    options: list[str] = field(default_factory=list)

    def to_args(self) -> list[str]:
        return [*self.options, "-i", self.path]


@dataclass
class TrackSegment:
    start_time: float
    duration: float
    source_start: float
    source_duration: float
    input_index: int | None
    is_gap: bool = False
    is_generator: bool = False
    generator_params: dict[str, Any] = field(default_factory=dict)
    speed_factor: float = 1.0
    is_freeze: bool = False
    effects: list[dict[str, Any]] = field(default_factory=list)
    transparent: bool = False


@dataclass
class TransitionInfo:
    position: int
    transition_type: str
    duration: float
    in_offset: float
    out_offset: float


class TimelineToFFmpeg:
    def __init__(
        self,
        timeline: dict[str, Any],
        asset_map: dict[str, str],
        preset: dict[str, Any],
        input_streams: dict[int, set[str]],
        temp_dir: Path | None = None,
        job_id: str | None = None,
    ):
        self.timeline = timeline
        self.asset_map = asset_map
        self.preset = preset
        self.input_streams = input_streams

        self.temp_dir = temp_dir or Path(os.environ.get("RENDER_TEMP_DIR", "/tmp/render"))
        self.job_id = job_id or "render"
        self._generator_dir = self.temp_dir / "generators" / self.job_id
        self._generator_dir.mkdir(parents=True, exist_ok=True)
        self._overlay_generator: OverlayGenerator | None = None
        self._generator_counter = 0

        self._inputs: list[InputSpec] = []
        self._input_index_map: dict[str, int] = {}
        self._video_filters: list[str] = []
        self._audio_filters: list[str] = []
        self._filter_counter = 0

    def build(self) -> tuple[list[InputSpec], str, list[str]]:
        self._collect_inputs()
        video_out = self._build_video_graph()
        audio_out = self._build_audio_graph()

        filter_complex = self._combine_filters()

        maps: list[str] = []
        if video_out:
            maps.append(f"[{video_out}]")
        if audio_out:
            maps.append(f"[{audio_out}]")
        return self._inputs, filter_complex, maps

    def _collect_inputs(self) -> None:
        self._inputs = []
        self._input_index_map = {}

        asset_ids = self._extract_asset_ids()
        for asset_id in asset_ids:
            path = self.asset_map.get(asset_id)
            if not path:
                continue
            if asset_id not in self._input_index_map:
                self._input_index_map[asset_id] = len(self._inputs)
                self._inputs.append(InputSpec(path=path))

    def _extract_asset_ids(self) -> list[str]:
        ids: list[str] = []
        tracks = self.timeline.get("tracks", {}).get("children", [])
        for track in tracks:
            if track.get("OTIO_SCHEMA") != "Track.1":
                continue
            for item in track.get("children", []):
                if item.get("OTIO_SCHEMA") != "Clip.1":
                    continue
                media_ref = item.get("media_reference", {})
                if media_ref.get("OTIO_SCHEMA") == "ExternalReference.1":
                    asset_id = media_ref.get("asset_id")
                    if asset_id:
                        ids.append(str(asset_id))
        return ids

    def _build_video_graph(self) -> str | None:
        tracks = [
            t
            for t in self.timeline.get("tracks", {}).get("children", [])
            if t.get("OTIO_SCHEMA") == "Track.1" and t.get("kind") == "Video"
        ]
        if not tracks:
            return None

        track_data: list[tuple[int, list[TrackSegment], list[TransitionInfo], float]] = []
        for track_idx, track in enumerate(tracks):
            track_name = str(track.get("name", ""))
            align_generator_start = track_name.lower() == "captions"
            transparent_gaps = track_idx > 0
            segments, transitions = self._extract_track_segments(
                track,
                align_generator_start=align_generator_start,
                transparent_gaps=transparent_gaps,
            )
            duration = sum(seg.duration for seg in segments)
            track_data.append((track_idx, segments, transitions, duration))

        if not track_data:
            return None

        base_duration = track_data[0][3]
        target_duration = base_duration or max((d for _, _, _, d in track_data), default=0)

        track_outputs: list[str] = []
        for track_idx, segments, transitions, duration in track_data:
            if track_idx > 0 and target_duration > duration:
                pad_duration = target_duration - duration
                segments.append(
                    TrackSegment(
                        start_time=duration,
                        duration=pad_duration,
                        source_start=0,
                        source_duration=pad_duration,
                        input_index=None,
                        is_gap=True,
                        transparent=True,
                    )
                )
            segment_outputs: list[str] = []
            segment_durations: list[float] = []
            for seg_idx, segment in enumerate(segments):
                seg_out = self._process_video_segment(segment, track_idx, seg_idx)
                if seg_out:
                    segment_outputs.append(seg_out)
                    segment_durations.append(segment.duration)
            if not segment_outputs:
                continue
            track_out = self._apply_video_transitions(
                segment_outputs, transitions, segment_durations
            )
            track_outputs.append(track_out)

        if not track_outputs:
            return None
        if len(track_outputs) == 1:
            return track_outputs[0]
        return self._overlay_video_tracks(track_outputs)

    def _build_audio_graph(self) -> str | None:
        tracks = [
            t
            for t in self.timeline.get("tracks", {}).get("children", [])
            if t.get("OTIO_SCHEMA") == "Track.1" and t.get("kind") == "Audio"
        ]
        if not tracks:
            return self._extract_audio_from_video()

        track_outputs: list[str] = []
        for track_idx, track in enumerate(tracks):
            segments, transitions = self._extract_track_segments(track)
            segment_outputs: list[str] = []
            segment_durations: list[float] = []
            for seg_idx, segment in enumerate(segments):
                seg_out = self._process_audio_segment(segment, track_idx, seg_idx)
                if seg_out:
                    segment_outputs.append(seg_out)
                    segment_durations.append(segment.duration)
            if not segment_outputs:
                continue
            track_out = self._apply_audio_transitions(
                segment_outputs, transitions, segment_durations
            )
            track_outputs.append(track_out)

        if not track_outputs:
            return None
        if len(track_outputs) == 1:
            return track_outputs[0]
        return self._mix_audio_tracks(track_outputs)

    def _extract_track_segments(
        self,
        track: dict[str, Any],
        align_generator_start: bool = False,
        transparent_gaps: bool = False,
    ) -> tuple[list[TrackSegment], list[TransitionInfo]]:
        segments: list[TrackSegment] = []
        transitions: list[TransitionInfo] = []
        position = 0
        current_time = 0.0

        for item in track.get("children", []):
            schema = item.get("OTIO_SCHEMA")
            if schema == "Transition.1":
                trans = self._parse_transition(item, position)
                if trans:
                    transitions.append(trans)
                continue

            if schema == "Gap.1":
                duration = self._duration_seconds(item.get("source_range"))
                segments.append(
                    TrackSegment(
                        start_time=current_time,
                        duration=duration,
                        source_start=0,
                        source_duration=duration,
                        input_index=None,
                        is_gap=True,
                        transparent=transparent_gaps,
                    )
                )
                current_time += duration
                position += 1
                continue

            if schema != "Clip.1":
                continue

            source_range = item.get("source_range", {})
            source_start = self._time_seconds(source_range.get("start_time"))
            source_duration = self._time_seconds(source_range.get("duration"))

            media_ref = item.get("media_reference", {})
            input_index: int | None = None
            is_generator = False
            generator_params: dict[str, Any] = {}

            if media_ref.get("OTIO_SCHEMA") == "ExternalReference.1":
                asset_id = str(media_ref.get("asset_id"))
                input_index = self._input_index_map.get(asset_id)
            elif media_ref.get("OTIO_SCHEMA") == "GeneratorReference.1":
                is_generator = True
                generator_params = {
                    "kind": media_ref.get("generator_kind", "SolidColor"),
                    "params": media_ref.get("parameters", {}),
                }
            else:
                input_index = None

            if is_generator and align_generator_start and source_start > current_time:
                gap_duration = source_start - current_time
                segments.append(
                    TrackSegment(
                        start_time=current_time,
                        duration=gap_duration,
                        source_start=0,
                        source_duration=gap_duration,
                        input_index=None,
                        is_gap=True,
                        transparent=transparent_gaps,
                    )
                )
                current_time += gap_duration
                position += 1

            speed_factor, is_freeze, effects = self._parse_effects(item.get("effects", []))

            segments.append(
                TrackSegment(
                    start_time=current_time,
                    duration=source_duration / speed_factor if speed_factor else source_duration,
                    source_start=source_start,
                    source_duration=source_duration,
                    input_index=input_index,
                    is_gap=input_index is None and not is_generator,
                    is_generator=is_generator,
                    generator_params=generator_params,
                    speed_factor=speed_factor,
                    is_freeze=is_freeze,
                    effects=effects,
                    transparent=bool(input_index is None and not is_generator and transparent_gaps),
                )
            )
            current_time += source_duration / speed_factor if speed_factor else source_duration
            position += 1

        return segments, transitions

    def _parse_transition(self, item: dict[str, Any], position: int) -> TransitionInfo | None:
        in_offset = self._time_seconds(item.get("in_offset"))
        out_offset = self._time_seconds(item.get("out_offset"))
        duration = in_offset + out_offset
        return TransitionInfo(
            position=position,
            transition_type=item.get("transition_type", "SMPTE_Dissolve"),
            duration=duration,
            in_offset=in_offset,
            out_offset=out_offset,
        )

    def _parse_effects(
        self, effects: list[dict[str, Any]]
    ) -> tuple[float, bool, list[dict[str, Any]]]:
        speed_factor = 1.0
        is_freeze = False
        effects_data: list[dict[str, Any]] = []

        for effect in effects:
            schema = effect.get("OTIO_SCHEMA")
            if schema == "LinearTimeWarp.1":
                speed_factor = effect.get("time_scalar", 1.0)
                effects_data.append({"type": "speed", "factor": speed_factor})
                continue
            if schema == "FreezeFrame.1":
                is_freeze = True
                effects_data.append({"type": "freeze"})
                continue
            effect_type = effect.get("metadata", {}).get("type") or effect.get("effect_name")
            effects_data.append(
                {
                    "type": str(effect_type),
                    "name": effect.get("effect_name"),
                    "metadata": effect.get("metadata", {}),
                }
            )

        return speed_factor, is_freeze, effects_data

    def _process_video_segment(
        self, segment: TrackSegment, track_idx: int, seg_idx: int
    ) -> str | None:
        label = f"v{track_idx}_{seg_idx}"
        if segment.is_gap:
            return self._generate_gap_video(segment, label)
        if segment.is_generator:
            return self._generate_generator_video(segment, label)
        if segment.input_index is None:
            return None

        filters: list[str] = []
        input_label = f"{segment.input_index}:v"
        filters.append(
            f"trim=start={segment.source_start}:duration={segment.source_duration}"
        )
        filters.append("setpts=PTS-STARTPTS")

        if segment.is_freeze:
            framerate = self._framerate()
            frame_duration = 1.0 / framerate if framerate > 0 else 0.0
            stop_duration = max(0.0, segment.duration - frame_duration)
            filters.append("select='eq(n,0)'")
            if stop_duration > 0:
                filters.append(
                    f"tpad=stop_mode=clone:stop_duration={stop_duration}"
                )
        elif segment.speed_factor != 1.0:
            pts_factor = 1.0 / segment.speed_factor
            filters.append(f"setpts={pts_factor}*PTS")

        width = self._video_width()
        height = self._video_height()
        filters.append(
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
        )
        filters.append("setsar=1")

        filter_chain = ",".join(filters)
        self._video_filters.append(f"[{input_label}]{filter_chain}[{label}]")
        return self._apply_video_effects(label, segment)

    def _process_audio_segment(
        self, segment: TrackSegment, track_idx: int, seg_idx: int
    ) -> str | None:
        label = f"a{track_idx}_{seg_idx}"

        if segment.is_gap or segment.is_generator:
            return self._generate_gap_audio(segment, label)

        if segment.input_index is None:
            return None

        if "a" not in self.input_streams.get(segment.input_index, set()):
            return self._generate_gap_audio(segment, label)

        filters: list[str] = []
        input_label = f"{segment.input_index}:a"
        filters.append(
            f"atrim=start={segment.source_start}:duration={segment.source_duration}"
        )
        filters.append("asetpts=PTS-STARTPTS")

        if segment.speed_factor != 1.0:
            filters.extend(self._build_atempo_chain(segment.speed_factor))

        filter_chain = ",".join(filters)
        self._audio_filters.append(f"[{input_label}]{filter_chain}[{label}]")
        return self._apply_audio_effects(label, segment)

    def _apply_video_effects(self, input_label: str, segment: TrackSegment) -> str:
        current = input_label
        effects = segment.effects or []
        if not effects:
            return current

        for effect in effects:
            effect_type = str(effect.get("type", "")).lower()
            metadata = effect.get("metadata") or {}
            if effect_type in {"speed", "freeze", ""}:
                continue
            if effect_type == "lut":
                current = self._apply_lut(current, metadata)
                continue
            if effect_type in {"grade", "color"}:
                current = self._apply_color_grade(current, metadata)
                continue
            if effect_type == "curves":
                current = self._apply_curves(current, metadata)
                continue
            if effect_type in {"white_balance", "wb"}:
                current = self._apply_white_balance(current, metadata)
                continue
            if effect_type == "blur":
                radius = metadata.get("radius", 8)
                current = self._apply_simple_video_filter(
                    current, f"boxblur=lr={radius}:cr={radius}"
                )
                continue
            if effect_type == "vignette":
                strength = float(metadata.get("strength", 0.5))
                if strength <= 0:
                    continue
                strength = min(1.0, strength)
                min_angle = math.pi / 12
                max_angle = math.pi / 3
                angle = min_angle + (max_angle - min_angle) * strength
                current = self._apply_simple_video_filter(
                    current, f"vignette=angle={angle:.4f}"
                )
                continue
            if effect_type == "grain":
                amount = metadata.get("amount", 0.2)
                current = self._apply_simple_video_filter(
                    current, f"noise=alls={amount}:allf=t+u"
                )
                continue
            if effect_type == "glow":
                current = self._apply_glow(current, metadata)
                continue
            if effect_type in {"chromatic_aberration", "chromatic"}:
                current = self._apply_chromatic_aberration(current, metadata)
                continue
            if effect_type == "sharpen":
                current = self._apply_sharpen(current, metadata)
                continue
            if effect_type in {"black_and_white", "bw", "monochrome"}:
                current = self._apply_simple_video_filter(current, "hue=s=0")
                continue
            if effect_type == "sepia":
                current = self._apply_sepia(current)
                continue
            if effect_type == "pixelate":
                current = self._apply_pixelate(current, metadata)
                continue
            if effect_type == "edge_glow":
                current = self._apply_edge_glow(current, metadata)
                continue
            if effect_type == "tint":
                current = self._apply_tint(current, metadata)
                continue
            if effect_type == "stabilize":
                strength = float(metadata.get("strength", 0.5))
                radius = max(2, int(20 * strength))
                current = self._apply_simple_video_filter(
                    current, f"deshake=rx={radius}:ry={radius}:edge=mirror"
                )
                continue
            if effect_type == "reframe":
                current = self._apply_reframe(current, metadata)
                continue
            if effect_type == "position":
                current = self._apply_position(current, metadata)
                continue
            if effect_type == "mask":
                current = self._apply_mask(current, metadata)
                continue
            if effect_type == "mask_blur":
                current = self._apply_mask_blur(current, metadata)
                continue
            if effect_type == "zoom":
                current = self._apply_zoom(current, metadata, segment)
                continue

        return current

    def _apply_audio_effects(self, input_label: str, segment: TrackSegment) -> str:
        current = input_label
        effects = segment.effects or []
        if not effects:
            return current

        for effect in effects:
            effect_type = str(effect.get("type", "")).lower()
            metadata = effect.get("metadata") or {}
            if effect_type == "ducking":
                current = self._apply_ducking(current, metadata)
                continue
            if effect_type == "loudness":
                current = self._apply_loudness(current, metadata)
                continue
            if effect_type == "volume":
                current = self._apply_volume(current, metadata)
                continue
            if effect_type == "fade":
                current = self._apply_audio_fade(current, metadata)
                continue

        return current

    def _apply_simple_video_filter(self, input_label: str, expr: str) -> str:
        output_label = f"vfx_{self._filter_counter}"
        self._filter_counter += 1
        self._video_filters.append(f"[{input_label}]{expr}[{output_label}]")
        return output_label

    def _apply_simple_audio_filter(self, input_label: str, expr: str) -> str:
        output_label = f"afx_{self._filter_counter}"
        self._filter_counter += 1
        self._audio_filters.append(f"[{input_label}]{expr}[{output_label}]")
        return output_label

    def _apply_lut(self, input_label: str, metadata: dict[str, Any]) -> str:
        path = metadata.get("path")
        if not path:
            return input_label
        intensity = float(metadata.get("intensity", 1.0))
        if intensity >= 0.999:
            return self._apply_simple_video_filter(
                input_label, f"lut3d=file={path}"
            )

        base_label = f"vlut_base_{self._filter_counter}"
        lut_label = f"vlut_src_{self._filter_counter}"
        lut_out = f"vlut_out_{self._filter_counter}"
        output_label = f"vlut_mix_{self._filter_counter}"
        self._filter_counter += 1

        self._video_filters.append(
            f"[{input_label}]split=2[{base_label}][{lut_label}]"
        )
        self._video_filters.append(f"[{lut_label}]lut3d=file={path}[{lut_out}]")
        self._video_filters.append(
            f"[{base_label}][{lut_out}]blend=all_mode=normal:all_opacity={intensity}"
            f"[{output_label}]"
        )
        return output_label

    def _apply_color_grade(self, input_label: str, metadata: dict[str, Any]) -> str:
        parts: list[str] = []
        if metadata.get("brightness") is not None:
            parts.append(f"brightness={metadata['brightness']}")
        if metadata.get("contrast") is not None:
            parts.append(f"contrast={metadata['contrast']}")
        if metadata.get("saturation") is not None:
            parts.append(f"saturation={metadata['saturation']}")
        if metadata.get("gamma") is not None:
            parts.append(f"gamma={metadata['gamma']}")
        if not parts:
            return input_label
        return self._apply_simple_video_filter(input_label, "eq=" + ":".join(parts))

    def _apply_curves(self, input_label: str, metadata: dict[str, Any]) -> str:
        preset = metadata.get("preset")
        points = metadata.get("points")
        if preset:
            expr = f"curves=preset={preset}"
        elif points:
            expr = f"curves={points}"
        else:
            return input_label
        return self._apply_simple_video_filter(input_label, expr)

    def _apply_white_balance(self, input_label: str, metadata: dict[str, Any]) -> str:
        red = metadata.get("red", 0)
        green = metadata.get("green", 0)
        blue = metadata.get("blue", 0)
        expr = f"colorbalance=rs={red}:gs={green}:bs={blue}"
        return self._apply_simple_video_filter(input_label, expr)

    def _apply_reframe(self, input_label: str, metadata: dict[str, Any]) -> str:
        canvas_w = self._video_width()
        canvas_h = self._video_height()
        width_value = self._normalize_to_pixels(metadata.get("width"), canvas_w)
        height_value = self._normalize_to_pixels(metadata.get("height"), canvas_h)
        width = None if width_value is None else max(1, int(round(width_value)))
        height = None if height_value is None else max(1, int(round(height_value)))
        if width is None or height is None:
            return input_label
        x_value = self._normalize_to_pixels(metadata.get("x"), canvas_w)
        y_value = self._normalize_to_pixels(metadata.get("y"), canvas_h)
        x = int(round(0 if x_value is None else x_value))
        y = int(round(0 if y_value is None else y_value))
        expr = f"crop={width}:{height}:{x}:{y},scale={canvas_w}:{canvas_h}"
        return self._apply_simple_video_filter(input_label, expr)

    def _apply_position(self, input_label: str, metadata: dict[str, Any]) -> str:
        canvas_w = self._video_width()
        canvas_h = self._video_height()
        width_value = self._normalize_to_pixels(metadata.get("width"), canvas_w)
        height_value = self._normalize_to_pixels(metadata.get("height"), canvas_h)
        width = canvas_w if width_value is None else max(1, int(round(width_value)))
        height = canvas_h if height_value is None else max(1, int(round(height_value)))
        x_value = self._normalize_to_pixels(metadata.get("x"), canvas_w)
        y_value = self._normalize_to_pixels(metadata.get("y"), canvas_h)
        x = int(round(0 if x_value is None else x_value))
        y = int(round(0 if y_value is None else y_value))
        expr = (
            f"scale={width}:{height},format=rgba,"
            f"pad={canvas_w}:{canvas_h}:{x}:{y}:color=0x00000000"
        )
        return self._apply_simple_video_filter(input_label, expr)

    def _apply_mask(self, input_label: str, metadata: dict[str, Any]) -> str:
        canvas_w = self._video_width()
        canvas_h = self._video_height()
        width_value = self._normalize_to_pixels(metadata.get("width"), canvas_w)
        height_value = self._normalize_to_pixels(metadata.get("height"), canvas_h)
        width = None if width_value is None else max(1, int(round(width_value)))
        height = None if height_value is None else max(1, int(round(height_value)))
        if width is None or height is None:
            return input_label
        x_value = self._normalize_to_pixels(metadata.get("x"), canvas_w)
        y_value = self._normalize_to_pixels(metadata.get("y"), canvas_h)
        x = int(round(0 if x_value is None else x_value))
        y = int(round(0 if y_value is None else y_value))
        expr = (
            f"crop={width}:{height}:{x}:{y},format=rgba,"
            f"pad={canvas_w}:{canvas_h}:{x}:{y}:color=0x00000000"
        )
        return self._apply_simple_video_filter(input_label, expr)

    def _apply_mask_blur(self, input_label: str, metadata: dict[str, Any]) -> str:
        canvas_w = self._video_width()
        canvas_h = self._video_height()
        width_value = self._normalize_to_pixels(metadata.get("width"), canvas_w)
        height_value = self._normalize_to_pixels(metadata.get("height"), canvas_h)
        width = None if width_value is None else max(1, int(round(width_value)))
        height = None if height_value is None else max(1, int(round(height_value)))
        if width is None or height is None:
            return input_label
        x_value = self._normalize_to_pixels(metadata.get("x"), canvas_w)
        y_value = self._normalize_to_pixels(metadata.get("y"), canvas_h)
        x = int(round(0 if x_value is None else x_value))
        y = int(round(0 if y_value is None else y_value))
        radius = metadata.get("radius", 8)

        base_label = f"vblur_base_{self._filter_counter}"
        blur_label = f"vblur_src_{self._filter_counter}"
        crop_label = f"vblur_crop_{self._filter_counter}"
        out_label = f"vblur_out_{self._filter_counter}"
        self._filter_counter += 1

        self._video_filters.append(
            f"[{input_label}]split=2[{base_label}][{blur_label}]"
        )
        self._video_filters.append(
            f"[{blur_label}]crop={width}:{height}:{x}:{y},boxblur=lr={radius}:cr={radius}"
            f"[{crop_label}]"
        )
        self._video_filters.append(
            f"[{base_label}][{crop_label}]overlay={x}:{y}[{out_label}]"
        )
        return out_label

    def _apply_zoom(
        self, input_label: str, metadata: dict[str, Any], segment: TrackSegment
    ) -> str:
        start_zoom = float(metadata.get("start_zoom", 1.0))
        end_zoom = float(metadata.get("end_zoom", 1.0))
        canvas_w = self._video_width()
        canvas_h = self._video_height()
        center_x = self._normalize_ratio(metadata.get("center_x"), canvas_w, 0.5)
        center_y = self._normalize_ratio(metadata.get("center_y"), canvas_h, 0.5)
        framerate = self._framerate()
        frames = max(1, int(segment.duration * framerate))

        zoom_expr = (
            f"if(eq(on,0),{start_zoom},"
            f"{start_zoom}+({end_zoom}-{start_zoom})*on/({frames}-1))"
        )
        x_expr = f"(iw - iw/zoom)*{center_x}"
        y_expr = f"(ih - ih/zoom)*{center_y}"
        expr = (
            f"zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}':"
            f"d={frames}:s={canvas_w}x{canvas_h}:fps={framerate}"
        )
        return self._apply_simple_video_filter(input_label, expr)

    def _apply_glow(self, input_label: str, metadata: dict[str, Any]) -> str:
        strength = float(metadata.get("strength", 0.6))
        strength = max(0.0, min(1.0, strength))
        blur = float(metadata.get("blur", 20))
        blur = max(0.1, blur)

        base_label = f"vglow_base_{self._filter_counter}"
        glow_label = f"vglow_src_{self._filter_counter}"
        blur_label = f"vglow_blur_{self._filter_counter}"
        out_label = f"vglow_out_{self._filter_counter}"
        self._filter_counter += 1

        self._video_filters.append(
            f"[{input_label}]split=2[{base_label}][{glow_label}]"
        )
        self._video_filters.append(
            f"[{glow_label}]gblur=sigma={blur}[{blur_label}]"
        )
        self._video_filters.append(
            f"[{base_label}][{blur_label}]blend=all_mode=screen:all_opacity={strength}"
            f"[{out_label}]"
        )
        return out_label

    def _apply_chromatic_aberration(
        self, input_label: str, metadata: dict[str, Any]
    ) -> str:
        amount = float(metadata.get("amount", 2.0))
        rh = metadata.get("red_x", amount)
        rv = metadata.get("red_y", amount)
        gh = metadata.get("green_x", -amount)
        gv = metadata.get("green_y", 0.0)
        bh = metadata.get("blue_x", 0.0)
        bv = metadata.get("blue_y", -amount)
        expr = (
            f"rgbashift=rh={rh}:rv={rv}:gh={gh}:gv={gv}:"
            f"bh={bh}:bv={bv}"
        )
        return self._apply_simple_video_filter(input_label, expr)

    def _apply_sharpen(self, input_label: str, metadata: dict[str, Any]) -> str:
        amount = float(metadata.get("amount", 1.0))
        radius = int(metadata.get("radius", 5))
        radius = max(3, min(radius, 15))
        expr = (
            f"unsharp=luma_msize_x={radius}:luma_msize_y={radius}:"
            f"luma_amount={amount}"
        )
        return self._apply_simple_video_filter(input_label, expr)

    def _apply_sepia(self, input_label: str) -> str:
        expr = (
            "colorchannelmixer=0.393:0.769:0.189:0:"
            "0.349:0.686:0.168:0:"
            "0.272:0.534:0.131:0"
        )
        return self._apply_simple_video_filter(input_label, expr)

    def _apply_pixelate(self, input_label: str, metadata: dict[str, Any]) -> str:
        block = int(metadata.get("block_size", 12))
        block = max(1, block)
        expr = (
            f"scale=iw/{block}:ih/{block}:flags=neighbor,"
            f"scale=iw:ih:flags=neighbor"
        )
        return self._apply_simple_video_filter(input_label, expr)

    def _apply_edge_glow(self, input_label: str, metadata: dict[str, Any]) -> str:
        strength = float(metadata.get("strength", 0.7))
        strength = max(0.0, min(1.0, strength))
        low = float(metadata.get("low", 0.1))
        high = float(metadata.get("high", 0.4))
        blur = float(metadata.get("blur", 2.0))

        base_label = f"vedge_base_{self._filter_counter}"
        edge_label = f"vedge_src_{self._filter_counter}"
        glow_label = f"vedge_glow_{self._filter_counter}"
        out_label = f"vedge_out_{self._filter_counter}"
        self._filter_counter += 1

        self._video_filters.append(
            f"[{input_label}]split=2[{base_label}][{edge_label}]"
        )
        edge_expr = f"edgedetect=low={low}:high={high}"
        if blur > 0:
            edge_expr += f",gblur=sigma={blur}"
        self._video_filters.append(f"[{edge_label}]{edge_expr}[{glow_label}]")
        self._video_filters.append(
            f"[{base_label}][{glow_label}]blend=all_mode=screen:all_opacity={strength}"
            f"[{out_label}]"
        )
        return out_label

    def _apply_tint(self, input_label: str, metadata: dict[str, Any]) -> str:
        if "color" in metadata:
            r, g, b = self._parse_hex_color(str(metadata.get("color")))
            amount = float(metadata.get("amount", 0.3))
            rs = (r - 0.5) * 2 * amount
            gs = (g - 0.5) * 2 * amount
            bs = (b - 0.5) * 2 * amount
            expr = f"colorbalance=rs={rs:.3f}:gs={gs:.3f}:bs={bs:.3f}"
            return self._apply_simple_video_filter(input_label, expr)

        red = metadata.get("red", 0)
        green = metadata.get("green", 0)
        blue = metadata.get("blue", 0)
        expr = f"colorbalance=rs={red}:gs={green}:bs={blue}"
        return self._apply_simple_video_filter(input_label, expr)

    def _parse_hex_color(self, value: str) -> tuple[float, float, float]:
        raw = value.strip()
        if raw.startswith("#"):
            raw = raw[1:]
        if len(raw) >= 6:
            try:
                r = int(raw[0:2], 16) / 255.0
                g = int(raw[2:4], 16) / 255.0
                b = int(raw[4:6], 16) / 255.0
                return r, g, b
            except ValueError:
                return 0.0, 0.0, 0.0
        return 0.0, 0.0, 0.0

    def _apply_ducking(self, input_label: str, metadata: dict[str, Any]) -> str:
        segments = metadata.get("segments", [])
        target_db = metadata.get("target_db", -16)
        if not segments:
            gain = 10 ** (target_db / 20)
            return self._apply_simple_audio_filter(input_label, f"volume={gain}")

        expr = "1"
        for segment in segments[::-1]:
            start = segment.get("start_ms", 0) / 1000.0
            end = segment.get("end_ms", 0) / 1000.0
            gain_db = segment.get("gain_db", target_db)
            gain = 10 ** (gain_db / 20)
            expr = f"if(between(t,{start},{end}),{gain},{expr})"
        return self._apply_simple_audio_filter(input_label, f"volume={expr}")

    def _apply_loudness(self, input_label: str, metadata: dict[str, Any]) -> str:
        target = metadata.get("target_lufs", -16)
        lra = metadata.get("lra", 11)
        true_peak = metadata.get("true_peak", -1.5)
        expr = f"loudnorm=I={target}:LRA={lra}:TP={true_peak}"
        return self._apply_simple_audio_filter(input_label, expr)

    def _apply_volume(self, input_label: str, metadata: dict[str, Any]) -> str:
        if "gain" in metadata:
            gain = metadata["gain"]
        else:
            gain_db = metadata.get("gain_db", 0)
            gain = 10 ** (gain_db / 20)
        return self._apply_simple_audio_filter(input_label, f"volume={gain}")

    def _apply_audio_fade(self, input_label: str, metadata: dict[str, Any]) -> str:
        fade_type = metadata.get("fade_type", "in")
        start_ms = metadata.get("start_ms", 0)
        duration_ms = metadata.get("duration_ms", 500)
        start = start_ms / 1000.0
        duration = duration_ms / 1000.0
        expr = f"afade=t={fade_type}:st={start}:d={duration}"
        return self._apply_simple_audio_filter(input_label, expr)

    def _get_overlay_generator(self) -> OverlayGenerator:
        if self._overlay_generator is None:
            self._overlay_generator = OverlayGenerator(
                width=self._video_width(),
                height=self._video_height(),
                fps=self._framerate(),
                output_dir=self._generator_dir,
            )
        return self._overlay_generator

    def _register_overlay_input(self, asset: OverlayAsset) -> int:
        options: list[str] = []
        if asset.is_sequence:
            options.extend([
                "-framerate",
                f"{asset.fps}",
                "-start_number",
                str(asset.start_number),
            ])
        else:
            options.extend(["-loop", "1", "-framerate", f"{asset.fps}"])
        self._inputs.append(InputSpec(path=asset.path, options=options))
        return len(self._inputs) - 1

    def _generate_graphics_overlay(
        self, kind: str, params: dict[str, Any], segment: TrackSegment, label: str
    ) -> str:
        self._generator_counter += 1
        safe_label = f"{label}_{self._generator_counter}"
        generator = self._get_overlay_generator()
        asset = generator.generate(kind, params, segment.duration, safe_label)
        input_index = self._register_overlay_input(asset)
        input_label = f"{input_index}:v"
        filters = [
            f"trim=duration={segment.duration}",
            "setpts=PTS-STARTPTS",
            "format=rgba",
            "setsar=1",
        ]
        self._video_filters.append(
            f"[{input_label}]{','.join(filters)}[{label}]"
        )
        return label

    def _generate_gap_video(self, segment: TrackSegment, label: str) -> str:
        width = self._video_width()
        height = self._video_height()
        framerate = self._framerate()
        if segment.transparent:
            self._video_filters.append(
                f"color=c=black@0.0:s={width}x{height}:d={segment.duration}:r={framerate},"
                f"format=rgba,setsar=1[{label}]"
            )
        else:
            self._video_filters.append(
                f"color=c=black:s={width}x{height}:d={segment.duration}:r={framerate},"
                f"setsar=1[{label}]"
            )
        return label

    def _generate_gap_audio(self, segment: TrackSegment, label: str) -> str:
        sample_rate = self.preset.get("audio", {}).get("sample_rate", 48000)
        channels = self.preset.get("audio", {}).get("channels", 2)
        self._audio_filters.append(
            f"anullsrc=r={sample_rate}:cl={'stereo' if channels == 2 else 'mono'},"
            f"atrim=duration={segment.duration}[{label}]"
        )
        return label

    def _generate_generator_video(self, segment: TrackSegment, label: str) -> str:
        kind = segment.generator_params.get("kind", "SolidColor")
        params = dict(segment.generator_params.get("params", {}) or {})
        width = self._video_width()
        height = self._video_height()
        framerate = self._framerate()

        kind_lower = str(kind).lower().replace("-", "_")
        if kind_lower == "callout":
            kind_lower = "call_out"
        if kind_lower == "lowerthird":
            kind_lower = "lower_third"
        if kind_lower == "progressbar":
            kind_lower = "progress_bar"
        asset_id = params.get("asset_id") or params.get("image_asset_id")
        if asset_id and not params.get("image_path"):
            asset_path = self.asset_map.get(str(asset_id))
            if asset_path:
                params["image_path"] = asset_path

        if kind_lower == "caption":
            if not self._should_use_drawtext(params):
                return self._generate_graphics_overlay("caption", params, segment, label)
            text = self._escape_drawtext(str(params.get("text", "")))
            font = params.get("font")
            size = params.get("size")
            if not isinstance(size, (int, float)) or size <= 0:
                size = 48
            color = params.get("color")
            if not color:
                color = "white"
            bg_color = params.get("bg_color")
            if isinstance(bg_color, str):
                bg_color = bg_color.strip()
                if not bg_color:
                    bg_color = None
                elif bg_color.lower() in {"transparent", "none", "clear"}:
                    bg_color = "black@0.0"
            x = params.get("x")
            if x is None or str(x).strip() == "":
                x = "(w-text_w)/2"
            y = params.get("y")
            if y is None or str(y).strip() == "":
                y = "h-120"

            drawtext_parts = [
                f"text='{text}'",
                f"fontsize={size}",
                f"fontcolor={color}",
                f"x={x}",
                f"y={y}",
            ]
            if font:
                if str(font).lower().endswith((".ttf", ".otf")):
                    drawtext_parts.append(f"fontfile={font}")
                else:
                    drawtext_parts.append(f"font={font}")
            if bg_color:
                drawtext_parts.append("box=1")
                drawtext_parts.append(f"boxcolor={bg_color}")
                drawtext_parts.append("boxborderw=8")

            drawtext = "drawtext=" + ":".join(drawtext_parts)
            self._video_filters.append(
                f"color=c=black@0.0:s={width}x{height}:d={segment.duration}:r={framerate},"
                f"format=rgba,{drawtext},setsar=1[{label}]"
            )
        elif kind_lower in {
            "title",
            "lower_third",
            "watermark",
            "call_out",
            "progress_bar",
            "animated_text",
            "shape",
        }:
            return self._generate_graphics_overlay(kind_lower, params, segment, label)
        elif kind_lower == "solidcolor":
            color = params.get("color", "black")
            self._video_filters.append(
                f"color=c={color}:s={width}x{height}:d={segment.duration}:r={framerate},"
                f"setsar=1[{label}]"
            )
        elif kind_lower == "bars":
            self._video_filters.append(
                f"smptebars=s={width}x{height}:d={segment.duration}:r={framerate},"
                f"setsar=1[{label}]"
            )
        else:
            self._video_filters.append(
                f"color=c=black:s={width}x{height}:d={segment.duration}:r={framerate},"
                f"setsar=1[{label}]"
            )

        return label

    def _apply_video_transitions(
        self,
        segments: list[str],
        transitions: list[TransitionInfo],
        segment_durations: list[float],
    ) -> str:
        if not transitions:
            return self._concat_video_segments(segments)

        result = segments[0]
        result_duration = segment_durations[0] if segment_durations else 0.0
        transition_idx = 0

        for i in range(1, len(segments)):
            out_label = f"vtrans_{self._filter_counter}"
            self._filter_counter += 1
            next_duration = (
                segment_durations[i] if i < len(segment_durations) else 0.0
            )

            trans = None
            if transition_idx < len(transitions):
                if transitions[transition_idx].position == i:
                    trans = transitions[transition_idx]
                    transition_idx += 1

            if trans:
                trans_type = self._map_transition_type(trans.transition_type)
                transition_duration = max(
                    0.0, min(trans.duration, result_duration, next_duration)
                )
                if transition_duration > 0:
                    offset = max(0.0, result_duration - transition_duration)
                    self._video_filters.append(
                        f"[{result}][{segments[i]}]xfade=transition={trans_type}:"
                        f"duration={transition_duration}:offset={offset}[{out_label}]"
                    )
                    result_duration = (
                        result_duration + next_duration - transition_duration
                    )
                else:
                    self._video_filters.append(
                        f"[{result}][{segments[i]}]concat=n=2:v=1:a=0[{out_label}]"
                    )
                    result_duration += next_duration
            else:
                self._video_filters.append(
                    f"[{result}][{segments[i]}]concat=n=2:v=1:a=0[{out_label}]"
                )
                result_duration += next_duration

            result = out_label

        return result

    def _apply_audio_transitions(
        self,
        segments: list[str],
        transitions: list[TransitionInfo],
        segment_durations: list[float],
    ) -> str:
        if not transitions:
            return self._concat_audio_segments(segments)

        result = segments[0]
        result_duration = segment_durations[0] if segment_durations else 0.0
        transition_idx = 0

        for i in range(1, len(segments)):
            out_label = f"atrans_{self._filter_counter}"
            self._filter_counter += 1
            next_duration = (
                segment_durations[i] if i < len(segment_durations) else 0.0
            )

            trans = None
            if transition_idx < len(transitions):
                if transitions[transition_idx].position == i:
                    trans = transitions[transition_idx]
                    transition_idx += 1

            if trans:
                transition_duration = max(
                    0.0, min(trans.duration, result_duration, next_duration)
                )
                if transition_duration > 0:
                    self._audio_filters.append(
                        f"[{result}][{segments[i]}]acrossfade=d={transition_duration}"
                        f"[{out_label}]"
                    )
                    result_duration = (
                        result_duration + next_duration - transition_duration
                    )
                else:
                    self._audio_filters.append(
                        f"[{result}][{segments[i]}]concat=n=2:v=0:a=1[{out_label}]"
                    )
                    result_duration += next_duration
            else:
                self._audio_filters.append(
                    f"[{result}][{segments[i]}]concat=n=2:v=0:a=1[{out_label}]"
                )
                result_duration += next_duration

            result = out_label

        return result

    def _concat_video_segments(self, segments: list[str]) -> str:
        if len(segments) == 1:
            return segments[0]
        out_label = f"vconcat_{self._filter_counter}"
        self._filter_counter += 1
        inputs = "".join(f"[{s}]" for s in segments)
        self._video_filters.append(
            f"{inputs}concat=n={len(segments)}:v=1:a=0[{out_label}]"
        )
        return out_label

    def _concat_audio_segments(self, segments: list[str]) -> str:
        if len(segments) == 1:
            return segments[0]
        out_label = f"aconcat_{self._filter_counter}"
        self._filter_counter += 1
        inputs = "".join(f"[{s}]" for s in segments)
        self._audio_filters.append(
            f"{inputs}concat=n={len(segments)}:v=0:a=1[{out_label}]"
        )
        return out_label

    def _overlay_video_tracks(self, tracks: list[str]) -> str:
        if len(tracks) == 1:
            return tracks[0]
        result = tracks[0]
        for i in range(1, len(tracks)):
            out_label = f"voverlay_{self._filter_counter}"
            self._filter_counter += 1
            self._video_filters.append(
                f"[{result}][{tracks[i]}]overlay=shortest=1[{out_label}]"
            )
            result = out_label
        return result

    def _mix_audio_tracks(self, tracks: list[str]) -> str:
        if len(tracks) == 1:
            return tracks[0]
        out_label = f"amix_{self._filter_counter}"
        self._filter_counter += 1
        inputs = "".join(f"[{t}]" for t in tracks)
        self._audio_filters.append(
            f"{inputs}amix=inputs={len(tracks)}:duration=longest[{out_label}]"
        )
        return out_label

    def _extract_audio_from_video(self) -> str | None:
        tracks = [
            t
            for t in self.timeline.get("tracks", {}).get("children", [])
            if t.get("OTIO_SCHEMA") == "Track.1" and t.get("kind") == "Video"
        ]
        if not tracks:
            return None
        segments, transitions = self._extract_track_segments(tracks[0])
        segment_outputs: list[str] = []
        segment_durations: list[float] = []
        for seg_idx, segment in enumerate(segments):
            seg_out = self._process_audio_segment(segment, 0, seg_idx)
            if seg_out:
                segment_outputs.append(seg_out)
                segment_durations.append(segment.duration)
        if not segment_outputs:
            return None
        return self._apply_audio_transitions(
            segment_outputs, transitions, segment_durations
        )

    def _build_atempo_chain(self, tempo: float) -> list[str]:
        filters: list[str] = []
        while tempo < 0.5 or tempo > 2.0:
            if tempo < 0.5:
                filters.append("atempo=0.5")
                tempo /= 0.5
            elif tempo > 2.0:
                filters.append("atempo=2.0")
                tempo /= 2.0
        if tempo != 1.0:
            filters.append(f"atempo={tempo}")
        return filters

    def _map_transition_type(self, trans_type: str) -> str:
        mapping = {
            "SMPTE_Dissolve": "dissolve",
            "FadeIn": "fade",
            "FadeOut": "fade",
            "Wipe": "wipeleft",
            "Slide": "slideleft",
            "Custom": "dissolve",
        }
        if trans_type in mapping:
            return mapping[trans_type]

        xfade_transitions = {
            "custom",
            "fade",
            "wipeleft",
            "wiperight",
            "wipeup",
            "wipedown",
            "slideleft",
            "slideright",
            "slideup",
            "slidedown",
            "circlecrop",
            "rectcrop",
            "distance",
            "fadeblack",
            "fadewhite",
            "radial",
            "smoothleft",
            "smoothright",
            "smoothup",
            "smoothdown",
            "circleopen",
            "circleclose",
            "vertopen",
            "vertclose",
            "horzopen",
            "horzclose",
            "dissolve",
            "pixelize",
            "diagtl",
            "diagtr",
            "diagbl",
            "diagbr",
            "hlslice",
            "hrslice",
            "vuslice",
            "vdslice",
            "hblur",
            "fadegrays",
            "wipetl",
            "wipetr",
            "wipebl",
            "wipebr",
            "squeezeh",
            "squeezev",
            "zoomin",
            "fadefast",
            "fadeslow",
            "hlwind",
            "hrwind",
            "vuwind",
            "vdwind",
            "coverleft",
            "coverright",
            "coverup",
            "coverdown",
            "revealleft",
            "revealright",
            "revealup",
            "revealdown",
        }
        lower = str(trans_type).lower()
        if lower == "custom":
            return "dissolve"
        if lower in xfade_transitions:
            return lower
        return "dissolve"

    def _combine_filters(self) -> str:
        return ";".join(self._video_filters + self._audio_filters)

    def _time_seconds(self, rational: dict[str, Any] | None) -> float:
        if not rational:
            return 0.0
        value = rational.get("value", 0)
        rate = rational.get("rate", 24)
        return value / rate if rate else 0.0

    def _duration_seconds(self, time_range: dict[str, Any] | None) -> float:
        if not time_range:
            return 0.0
        return self._time_seconds(time_range.get("duration"))

    def _normalize_to_pixels(
        self, value: float | None, max_value: int
    ) -> float | None:
        if value is None:
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if 0.0 <= numeric <= 1.0:
            return numeric * max_value
        return numeric

    def _normalize_ratio(
        self, value: float | None, max_value: int, default: float
    ) -> float:
        if value is None:
            return default
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return default
        if 0.0 <= numeric <= 1.0:
            ratio = numeric
        elif max_value > 0:
            ratio = numeric / max_value
        else:
            ratio = default
        return max(0.0, min(1.0, ratio))

    def _video_width(self) -> int:
        return int(self.preset.get("video", {}).get("width") or 1920)

    def _video_height(self) -> int:
        return int(self.preset.get("video", {}).get("height") or 1080)

    def _framerate(self) -> float:
        value = self.preset.get("video", {}).get("framerate")
        if value:
            try:
                return float(value)
            except (TypeError, ValueError):
                return 24.0
        meta = self.timeline.get("metadata", {})
        rate = meta.get("default_rate", 24.0)
        try:
            return float(rate)
        except (TypeError, ValueError):
            return 24.0

    def _should_use_drawtext(self, params: dict[str, Any]) -> bool:
        engine = str(params.get("engine", "")).lower()
        if engine in {"ffmpeg", "drawtext"}:
            return True
        for key in ("x", "y"):
            if self._is_ffmpeg_expr(params.get(key)):
                return True
        return False

    def _is_ffmpeg_expr(self, value: Any) -> bool:
        if not isinstance(value, str):
            return False
        stripped = value.strip().lower()
        if stripped in {"", "left", "right", "top", "bottom", "center", "middle"}:
            return False
        try:
            float(stripped)
            return False
        except ValueError:
            return True

    def _escape_drawtext(self, value: str) -> str:
        return (
            value.replace("\\", "\\\\")
            .replace(":", "\\:")
            .replace("'", "\\'")
        )


class FFmpegRenderer:
    def __init__(self, manifest_dict: dict[str, Any]):
        self.manifest = RenderManifest(
            job_id=manifest_dict["job_id"],
            project_id=manifest_dict["project_id"],
            timeline_version=manifest_dict["timeline_version"],
            timeline_snapshot=manifest_dict["timeline_snapshot"],
            asset_map=manifest_dict["asset_map"],
            preset=manifest_dict["preset"],
            input_bucket=manifest_dict["input_bucket"],
            output_bucket=manifest_dict["output_bucket"],
            output_path=manifest_dict["output_path"],
            start_frame=manifest_dict.get("start_frame"),
            end_frame=manifest_dict.get("end_frame"),
            callback_url=manifest_dict.get("callback_url"),
        )
        self.temp_dir = Path(os.environ.get("RENDER_TEMP_DIR", "/tmp/render"))
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        self.inputs_dir = Path(os.environ.get("RENDER_INPUT_DIR", "/inputs"))
        self.outputs_dir = Path(os.environ.get("RENDER_OUTPUT_DIR", "/outputs"))

        self._storage_client: storage.Client | None = None
        self._ffmpeg_bin = os.environ.get("FFMPEG_BIN", "ffmpeg")
        self._ffprobe_bin = os.environ.get("FFPROBE_BIN", "ffprobe")
        self._available_gpu_encoders: dict[str, set[str]] | None = None


    def render(
        self,
        progress_callback: Callable[[int, str | None], None] | None = None,
    ) -> dict[str, Any]:
        logger.info(f"Starting render for job {self.manifest.job_id}")

        local_asset_map = self._resolve_asset_paths()
        external_asset_ids = self._extract_external_asset_ids()
        input_streams = self._probe_streams(local_asset_map, external_asset_ids)
        self._resolve_effect_assets(local_asset_map)

        if progress_callback:
            progress_callback(5, "Resolved asset paths")

        ffmpeg_cmd = self._build_ffmpeg_command(local_asset_map, input_streams)

        if progress_callback:
            progress_callback(10, "Built FFmpeg command")

        logger.info("FFmpeg command: %s", self._format_command(ffmpeg_cmd))

        output_path = Path(self._execute_ffmpeg(ffmpeg_cmd, progress_callback))
        output_duration = self._probe_output_duration(output_path)
        if output_duration is not None:
            logger.info("Output duration: %.3fs", output_duration)
            if output_duration <= 0.05:
                raise RenderError("FFmpeg produced zero-duration output")
        output_url = self._upload_output(output_path)

        logger.info(f"Render complete: {output_path}")

        return {
            "output_path": str(output_path),
            "output_url": output_url,
            "output_size_bytes": output_path.stat().st_size if output_path.exists() else None,
        }


    def _resolve_asset_paths(self) -> dict[str, str]:
        local_paths = {}

        for asset_id, gcs_path in self.manifest.asset_map.items():
            asset_path = Path(gcs_path)
            if asset_path.is_absolute():
                local_path = asset_path
            else:
                bucket_name, blob_path = self._parse_gcs_path(
                    gcs_path, self.manifest.input_bucket
                )
                local_path = self.inputs_dir / blob_path

                if not local_path.exists():
                    self._download_asset(bucket_name, blob_path, local_path)

            if not local_path.exists():
                raise RenderError(f"Asset not found: {local_path}")

            local_paths[asset_id] = str(local_path)
            logger.debug(f"Asset {asset_id}: {local_path}")

        return local_paths

    def _extract_external_asset_ids(self) -> list[str]:
        ids: list[str] = []
        seen: set[str] = set()
        tracks = self.manifest.timeline_snapshot.get("tracks", {}).get("children", [])
        for track in tracks:
            if track.get("OTIO_SCHEMA") != "Track.1":
                continue
            for item in track.get("children", []):
                if item.get("OTIO_SCHEMA") != "Clip.1":
                    continue
                media_ref = item.get("media_reference", {})
                if media_ref.get("OTIO_SCHEMA") == "ExternalReference.1":
                    asset_id = media_ref.get("asset_id")
                    if asset_id:
                        asset_key = str(asset_id)
                        if asset_key not in seen:
                            ids.append(asset_key)
                            seen.add(asset_key)
        return ids

    def _resolve_effect_assets(self, local_asset_map: dict[str, str]) -> None:
        tracks = self.manifest.timeline_snapshot.get("tracks", {}).get("children", [])
        for track in tracks:
            for item in track.get("children", []):
                if item.get("OTIO_SCHEMA") != "Clip.1":
                    continue
                for effect in item.get("effects", []):
                    metadata = effect.get("metadata") or {}
                    path = metadata.get("path")
                    if path:
                        metadata["path"] = self._download_effect_asset(path)
                        effect["metadata"] = metadata
                media_ref = item.get("media_reference", {})
                if media_ref.get("OTIO_SCHEMA") == "GeneratorReference.1":
                    params = media_ref.get("parameters", {})
                    font = params.get("font")
                    if font:
                        params["font"] = self._download_effect_asset(font)
                    for key in ("image_path", "logo_path", "mask_path"):
                        if params.get(key):
                            params[key] = self._download_effect_asset(params[key])
                    asset_id = params.get("asset_id") or params.get("image_asset_id")
                    if asset_id:
                        asset_path = local_asset_map.get(str(asset_id))
                        if asset_path and not params.get("image_path"):
                            params["image_path"] = asset_path
                    media_ref["parameters"] = params
                    item["media_reference"] = media_ref

    def _download_effect_asset(self, path: str) -> str:
        if path.startswith("gs://"):
            bucket_name, blob_path = self._parse_gcs_path(path, self.manifest.input_bucket)
            local_path = self.temp_dir / "effects" / Path(blob_path).name
            local_path.parent.mkdir(parents=True, exist_ok=True)
            if not local_path.exists():
                self._download_asset(bucket_name, blob_path, local_path)
            return str(local_path)
        return path


    def _probe_streams(
        self, asset_map: dict[str, str], asset_ids: list[str] | None = None
    ) -> dict[int, set[str]]:
        streams: dict[int, set[str]] = {}

        if asset_ids is None:
            items = list(asset_map.items())
        else:
            items = [(asset_id, asset_map[asset_id]) for asset_id in asset_ids if asset_id in asset_map]

        for idx, (_, asset_path) in enumerate(items):
            cmd = [
                self._ffprobe_bin,
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "json",
                asset_path,
            ]
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                data = json.loads(result.stdout)
                stream_types = {
                    stream.get("codec_type") for stream in data.get("streams", [])
                }
                streams[idx] = {s for s in stream_types if s}
            except (FileNotFoundError, subprocess.CalledProcessError, json.JSONDecodeError):
                streams[idx] = self._probe_streams_with_ffmpeg(asset_path)

        return streams

    def _probe_streams_with_ffmpeg(self, asset_path: str) -> set[str]:
        cmd = [self._ffmpeg_bin, "-hide_banner", "-i", asset_path]
        result = subprocess.run(cmd, capture_output=True, text=True)
        output = result.stderr or ""
        stream_types: set[str] = set()
        if "Video:" in output:
            stream_types.add("video")
        if "Audio:" in output:
            stream_types.add("audio")
        return stream_types

    def _download_asset(
        self, bucket_name: str, blob_path: str, local_path: Path
    ) -> None:
        client = self._get_storage_client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_path)

        local_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            blob.download_to_filename(str(local_path))
        except Exception as exc:
            raise RenderError(f"Failed to download gs://{bucket_name}/{blob_path}") from exc

    def _parse_gcs_path(self, gcs_path: str, fallback_bucket: str) -> tuple[str, str]:
        if gcs_path.startswith("gs://"):
            stripped = gcs_path[5:]
            parts = stripped.split("/", 1)
            if len(parts) != 2:
                raise RenderError(f"Invalid GCS path: {gcs_path}")
            return parts[0], parts[1]

        if not fallback_bucket:
            raise RenderError("input_bucket is required for GCS asset paths")
        return fallback_bucket, gcs_path

    def _get_storage_client(self) -> storage.Client:
        if self._storage_client:
            return self._storage_client

        credentials_json = os.environ.get("GCP_CREDENTIALS")
        if not credentials_json:
            self._storage_client = storage.Client()
            return self._storage_client

        try:
            credentials_info = json.loads(credentials_json)
        except json.JSONDecodeError as exc:
            raise RenderError("Invalid GCP_CREDENTIALS JSON") from exc

        credentials = service_account.Credentials.from_service_account_info(
            credentials_info
        )
        self._storage_client = storage.Client(
            credentials=credentials, project=credentials_info.get("project_id")
        )
        return self._storage_client

    def _upload_output(self, output_path: Path) -> str | None:
        if not output_path.exists():
            raise RenderError(f"Render output not found: {output_path}")

        output_bucket = self.manifest.output_bucket
        if not output_bucket or output_bucket == "local":
            logger.info("Skipping GCS upload for local output bucket")
            return None

        if Path(self.manifest.output_path).is_absolute():
            logger.info("Skipping GCS upload for absolute output path")
            return None

        bucket_name, blob_path = self._parse_gcs_path(
            self.manifest.output_path, output_bucket
        )
        client = self._get_storage_client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_path)

        try:
            blob.upload_from_filename(str(output_path))
        except Exception as exc:
            raise RenderError(
                f"Failed to upload render output to gs://{bucket_name}/{blob_path}"
            ) from exc
        return f"gs://{bucket_name}/{blob_path}"


    def _build_ffmpeg_command(
        self,
        asset_map: dict[str, str],
        input_streams: dict[int, set[str]],
    ) -> list[str]:
        timeline = self.manifest.timeline_snapshot
        preset = self.manifest.preset

        output_path = Path(self.manifest.output_path)
        if not output_path.is_absolute():
            output_path = self.outputs_dir / self.manifest.output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)


        cmd = [self._ffmpeg_bin, "-y"]

        inputs, filter_complex, maps = self._build_filter_graph(
            timeline, asset_map, input_streams
        )

        for input_entry in inputs:
            cmd.extend(input_entry.to_args())

        if filter_complex:
            cmd.extend(["-filter_complex", filter_complex])

        for m in maps:
            cmd.extend(["-map", m])

        cmd.extend(self._build_encoding_options(preset))
        cmd.extend(self._build_trim_options(preset))

        cmd.append(str(output_path))

        return cmd

    def _build_filter_graph(
        self,
        timeline: dict[str, Any],
        asset_map: dict[str, str],
        input_streams: dict[int, set[str]],
    ) -> tuple[list[InputSpec], str, list[str]]:
        builder = TimelineToFFmpeg(
            timeline,
            asset_map,
            self.manifest.preset,
            input_streams,
            temp_dir=self.temp_dir,
            job_id=self.manifest.job_id,
        )
        inputs, filter_complex, maps = builder.build()

        if not filter_complex and inputs:
            maps = ["0:v", "0:a"]

        return inputs, filter_complex, maps

    def _detect_available_gpu_encoders(self) -> dict[str, set[str]]:
        if self._available_gpu_encoders is not None:
            return self._available_gpu_encoders

        backend_encoders: dict[str, set[str]] = {
            "nvidia": set(),
            "amd": set(),
            "apple": set(),
        }
        encoder_map = {
            "h264_nvenc": ("nvidia", "h264"),
            "hevc_nvenc": ("nvidia", "h265"),
            "h264_amf": ("amd", "h264"),
            "hevc_amf": ("amd", "h265"),
            "h264_videotoolbox": ("apple", "h264"),
            "hevc_videotoolbox": ("apple", "h265"),
        }

        try:
            result = subprocess.run(
                [self._ffmpeg_bin, "-hide_banner", "-encoders"],
                capture_output=True,
                text=True,
                check=True,
            )
            output = result.stdout or ""
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            logger.warning("Failed to probe FFmpeg encoders: %s", exc)
            self._available_gpu_encoders = backend_encoders
            return backend_encoders

        for encoder_name, (backend, codec) in encoder_map.items():
            if encoder_name in output:
                backend_encoders[backend].add(codec)

        self._available_gpu_encoders = backend_encoders
        return backend_encoders

    def _normalize_gpu_backend(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip().lower()
        if normalized in {"nvidia", "amd", "apple"}:
            return normalized
        return None

    def _get_gpu_encoder_name(self, backend: str, codec: str) -> str | None:
        encoder_names = {
            ("nvidia", "h264"): "h264_nvenc",
            ("nvidia", "h265"): "hevc_nvenc",
            ("amd", "h264"): "h264_amf",
            ("amd", "h265"): "hevc_amf",
            ("apple", "h264"): "h264_videotoolbox",
            ("apple", "h265"): "hevc_videotoolbox",
        }
        return encoder_names.get((backend, codec))

    def _select_gpu_backend_and_encoder(
        self,
        preset: dict[str, Any],
        codec: str,
    ) -> tuple[str | None, str | None]:
        requested_backend = self._normalize_gpu_backend(preset.get("gpu_backend"))
        available = self._detect_available_gpu_encoders()

        preferred_backends = ["nvidia", "amd", "apple"]
        if platform.system() == "Darwin":
            preferred_backends = ["apple", "nvidia", "amd"]

        if requested_backend:
            if codec in available.get(requested_backend, set()):
                return requested_backend, self._get_gpu_encoder_name(requested_backend, codec)
            logger.warning(
                "Requested GPU backend '%s' does not support %s. Falling back.",
                requested_backend,
                codec,
            )

        for backend in preferred_backends:
            if codec in available.get(backend, set()):
                return backend, self._get_gpu_encoder_name(backend, codec)

        return None, None

    def _build_encoding_options(self, preset: dict[str, Any]) -> list[str]:
        options = []
        video = preset.get("video", {})
        audio = preset.get("audio", {})
        use_gpu = preset.get("use_gpu", False)

        codec = video.get("codec", "h264")
        video_encoder = ""
        selected_backend: str | None = None
        if use_gpu:
            selected_backend, video_encoder = self._select_gpu_backend_and_encoder(
                preset,
                codec,
            )
            if video_encoder:
                options.extend(["-c:v", video_encoder])
            else:
                logger.warning(
                    "GPU encoding requested, but no compatible %s hardware encoder is available. Using CPU encoder.",
                    codec,
                )
                use_gpu = False

        if not use_gpu:
            if codec == "h264":
                video_encoder = "libx264"
                options.extend(["-c:v", video_encoder])
            elif codec == "h265":
                video_encoder = "libx265"
                options.extend(["-c:v", video_encoder])

        if video_encoder:
            logger.info("Using video encoder: %s", video_encoder)
        if selected_backend:
            logger.info("Using GPU backend: %s", selected_backend)

        crf = video.get("crf", 23)
        if use_gpu and video_encoder and video_encoder.endswith("_nvenc"):
            options.extend(["-cq", str(crf)])
        elif not use_gpu:
            options.extend(["-crf", str(crf)])
        else:
            logger.info(
                "Skipping CRF/CQ option for encoder '%s' (backend-managed quality)",
                video_encoder,
            )

        enc_preset = video.get("preset", "medium")
        if use_gpu and video_encoder and video_encoder.endswith("_nvenc"):
            nvenc_map = {
                "ultrafast": "fast",
                "superfast": "fast",
                "veryfast": "fast",
                "faster": "fast",
                "fast": "fast",
                "medium": "medium",
                "slow": "slow",
                "slower": "slow",
                "veryslow": "slow",
            }
            enc_preset = nvenc_map.get(enc_preset, "medium")
            options.extend(["-preset", enc_preset])
        elif not use_gpu:
            options.extend(["-preset", enc_preset])
        else:
            logger.info(
                "Skipping -preset for encoder '%s' (unsupported encoder preset mapping)",
                video_encoder,
            )

        pix_fmt = video.get("pixel_format", "yuv420p")
        options.extend(["-pix_fmt", pix_fmt])

        audio_codec = audio.get("codec", "aac")
        if audio_codec == "aac":
            options.extend(["-c:a", "aac"])
        elif audio_codec == "mp3":
            options.extend(["-c:a", "libmp3lame"])

        audio_bitrate = audio.get("bitrate", "192k")
        options.extend(["-b:a", audio_bitrate])

        options.extend(["-movflags", "+faststart"])

        return options

    def _build_trim_options(self, preset: dict[str, Any]) -> list[str]:
        start_frame = self.manifest.start_frame
        end_frame = self.manifest.end_frame
        if start_frame is None and end_frame is None:
            return []

        framerate = preset.get("video", {}).get("framerate") or 24
        try:
            framerate = float(framerate)
        except (TypeError, ValueError):
            framerate = 24.0

        start_frame = max(0, int(start_frame or 0))
        start_time = start_frame / framerate

        options = []
        if start_frame > 0:
            options.extend(["-ss", f"{start_time:.3f}"])

        if end_frame is not None:
            end_frame = max(start_frame, int(end_frame))
            duration_frames = max(0, end_frame - start_frame)
            duration_time = duration_frames / framerate
            if duration_time > 0:
                options.extend(["-t", f"{duration_time:.3f}"])

        return options

    def _execute_ffmpeg(
        self,
        cmd: list[str],
        progress_callback: Callable[[int, str | None], None] | None = None,
    ) -> str:
        output_path = cmd[-1]

        cmd_with_progress = cmd[:-1] + ["-progress", "pipe:1", cmd[-1]]

        logger.info("Executing FFmpeg...")
        logger.debug(f"Command: {' '.join(cmd_with_progress)}")

        try:
            process = subprocess.Popen(
                cmd_with_progress,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            duration = None
            last_progress = 10
            output_tail: list[str] = []

            if process.stdout is None:
                raise RenderError("FFmpeg did not provide a stdout stream")

            for line in process.stdout:
                line = line.strip()
                if line:
                    output_tail.append(line)
                    if len(output_tail) > 200:
                        output_tail = output_tail[-200:]

                if line.startswith("Duration:"):
                    match = re.search(r"Duration: (\d+):(\d+):(\d+)", line)
                    if match:
                        h, m, s = map(int, match.groups())
                        duration = h * 3600 + m * 60 + s

                if line.startswith("out_time_ms="):
                    try:
                        time_ms = int(line.split("=")[1])
                        time_sec = time_ms / 1000000

                        if duration and duration > 0:
                            pct = min(95, 10 + int((time_sec / duration) * 85))
                            if pct > last_progress and progress_callback:
                                progress_callback(pct, None)
                                last_progress = pct
                    except (ValueError, IndexError):
                        pass

            process.wait()

            if process.returncode != 0:
                tail_text = "\n".join(output_tail[-40:])
                raise RenderError(
                    f"FFmpeg failed (code {process.returncode}). Output:\n{tail_text}"
                )
            if output_tail:
                logger.info("FFmpeg output (tail): %s", "\n".join(output_tail[-20:]))

            if progress_callback:
                progress_callback(95, "Finalizing output")

            return output_path

        except subprocess.SubprocessError as e:
            raise RenderError(f"Failed to execute FFmpeg: {e}")

    def _probe_output_duration(self, output_path: Path) -> float | None:
        cmd = [
            self._ffprobe_bin,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(output_path),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            value = result.stdout.strip()
            if not value:
                return None
            return float(value)
        except (FileNotFoundError, subprocess.CalledProcessError, ValueError) as exc:
            logger.warning("Failed to probe output duration: %s", exc)
            return None

    def _format_command(self, cmd: list[str]) -> str:
        text = " ".join(cmd)
        if len(text) > 4000:
            return f"{text[:4000]}... [truncated]"
        return text

    def cleanup(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)
