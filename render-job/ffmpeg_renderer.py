#!/usr/bin/env python3
import copy
import json
import logging
import math
import os
import platform
import re
import shutil
import subprocess
import threading
import time
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
    output_variants: list[dict[str, Any]] = field(default_factory=list)


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

        decode_options = self._input_decode_options()
        asset_ids = self._extract_asset_ids()
        for asset_id in asset_ids:
            path = self.asset_map.get(asset_id)
            if not path:
                continue
            if asset_id not in self._input_index_map:
                self._input_index_map[asset_id] = len(self._inputs)
                self._inputs.append(InputSpec(path=path, options=list(decode_options)))

    def _input_decode_options(self) -> list[str]:
        if not self.preset.get("use_gpu"):
            return []
        return ["-hwaccel", "auto"]

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
            if str(effect_type).lower() == "speed_ramp":
                metadata = effect.get("metadata", {})
                avg_speed = self._estimate_speed_ramp_factor(metadata)
                if avg_speed > 0:
                    speed_factor = avg_speed
            effects_data.append(
                {
                    "type": str(effect_type),
                    "name": effect.get("effect_name"),
                    "metadata": effect.get("metadata", {}),
                }
            )

        return speed_factor, is_freeze, effects_data

    def _estimate_speed_ramp_factor(self, metadata: dict[str, Any]) -> float:
        keyframes = metadata.get("keyframes") or []
        if not isinstance(keyframes, list) or not keyframes:
            speed = metadata.get("speed")
            if speed is None:
                return 1.0
            try:
                return max(0.01, float(speed))
            except (TypeError, ValueError):
                return 1.0

        points: list[tuple[float, float]] = []
        for point in keyframes:
            if not isinstance(point, dict):
                continue
            raw_t = point.get("time_ms", point.get("time", point.get("t", 0)))
            raw_s = point.get("speed", point.get("value", 1.0))
            try:
                t = float(raw_t)
                s = max(0.01, float(raw_s))
            except (TypeError, ValueError):
                continue
            if t > 1000:
                t = t / 1000.0
            points.append((max(0.0, t), s))

        if not points:
            return 1.0

        points.sort(key=lambda p: p[0])
        total_input = 0.0
        total_output = 0.0
        for idx, (start_t, speed) in enumerate(points):
            end_t = points[idx + 1][0] if idx + 1 < len(points) else start_t + 0.001
            interval = max(0.0, end_t - start_t)
            total_input += interval
            total_output += interval / speed

        if total_input <= 0 or total_output <= 0:
            return points[-1][1]

        return max(0.01, total_input / total_output)

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
        else:
            has_speed_ramp = any(
                str(effect.get("type", "")).lower() == "speed_ramp"
                for effect in (segment.effects or [])
            )
            if segment.speed_factor != 1.0 and not has_speed_ramp:
                pts_factor = 1.0 / segment.speed_factor
                filters.append(f"setpts={pts_factor}*PTS")

        width = self._video_width()
        height = self._video_height()
        filters.append(
            f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,"
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
            if effect_type in {"video_fade", "fade"}:
                apply_to = str(metadata.get("apply_to", "audio" if effect_type == "fade" else "video")).lower()
                if apply_to in {"video", "both"} or effect_type == "video_fade":
                    current = self._apply_video_fade(current, metadata, segment)
                continue
            if effect_type in {"rotate", "rotation"}:
                current = self._apply_rotate(current, metadata)
                continue
            if effect_type == "flip":
                current = self._apply_flip(current, metadata)
                continue
            if effect_type in {"chroma_key", "chromakey", "green_screen", "key"}:
                current = self._apply_chroma_key(current, metadata)
                continue
            if effect_type == "speed_ramp":
                current = self._apply_speed_ramp(current, metadata, segment)
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
            if effect_type in {"eq", "equalizer"}:
                current = self._apply_audio_equalizer(current, metadata)
                continue
            if effect_type in {"noise_reduction", "denoise", "noise"}:
                current = self._apply_audio_noise_reduction(current, metadata)
                continue
            if effect_type in {"compressor", "compression"}:
                current = self._apply_audio_compressor(current, metadata)
                continue
            if effect_type in {"limiter", "limit"}:
                current = self._apply_audio_limiter(current, metadata)
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

    def _apply_video_fade(
        self, input_label: str, metadata: dict[str, Any], segment: TrackSegment
    ) -> str:
        fade_type = str(metadata.get("fade_type", "in")).lower()

        in_start_ms = metadata.get("in_start_ms", metadata.get("start_ms", 0))
        in_duration_ms = metadata.get("in_duration_ms", metadata.get("duration_ms", 500))
        out_start_ms = metadata.get("out_start_ms")
        out_duration_ms = metadata.get("out_duration_ms", metadata.get("duration_ms", 500))

        try:
            in_start = max(0.0, float(in_start_ms) / 1000.0)
        except (TypeError, ValueError):
            in_start = 0.0
        try:
            in_duration = max(0.001, float(in_duration_ms) / 1000.0)
        except (TypeError, ValueError):
            in_duration = 0.5
        try:
            out_duration = max(0.001, float(out_duration_ms) / 1000.0)
        except (TypeError, ValueError):
            out_duration = 0.5

        if out_start_ms is None:
            out_start = max(0.0, segment.duration - out_duration)
        else:
            try:
                out_start = max(0.0, float(out_start_ms) / 1000.0)
            except (TypeError, ValueError):
                out_start = max(0.0, segment.duration - out_duration)

        filters: list[str] = []
        if fade_type in {"in", "both", "inout", "in_out"}:
            filters.append(f"fade=t=in:st={in_start:.3f}:d={in_duration:.3f}")
        if fade_type in {"out", "both", "inout", "in_out"}:
            filters.append(f"fade=t=out:st={out_start:.3f}:d={out_duration:.3f}")

        if not filters:
            return input_label
        return self._apply_simple_video_filter(input_label, ",".join(filters))

    def _apply_rotate(self, input_label: str, metadata: dict[str, Any]) -> str:
        angle_value = metadata.get("angle", metadata.get("degrees", 0))
        try:
            angle = float(angle_value)
        except (TypeError, ValueError):
            return input_label

        normalized = angle % 360
        if abs(normalized) < 1e-6:
            return input_label

        if abs(normalized - 90) < 1e-6:
            return self._apply_simple_video_filter(input_label, "transpose=1")
        if abs(normalized - 180) < 1e-6:
            return self._apply_simple_video_filter(input_label, "hflip,vflip")
        if abs(normalized - 270) < 1e-6:
            return self._apply_simple_video_filter(input_label, "transpose=2")

        fill = str(metadata.get("fillcolor", "black@0.0"))
        expr = (
            f"rotate={angle}*PI/180:ow=rotw({angle}*PI/180):"
            f"oh=roth({angle}*PI/180):fillcolor={fill}"
        )
        return self._apply_simple_video_filter(input_label, expr)

    def _apply_flip(self, input_label: str, metadata: dict[str, Any]) -> str:
        direction = str(metadata.get("direction", "horizontal")).lower()
        horizontal = bool(metadata.get("horizontal", direction in {"horizontal", "both"}))
        vertical = bool(metadata.get("vertical", direction in {"vertical", "both"}))

        if horizontal and vertical:
            return self._apply_simple_video_filter(input_label, "hflip,vflip")
        if horizontal:
            return self._apply_simple_video_filter(input_label, "hflip")
        if vertical:
            return self._apply_simple_video_filter(input_label, "vflip")
        return input_label

    def _apply_chroma_key(self, input_label: str, metadata: dict[str, Any]) -> str:
        color = str(metadata.get("color", "#00ff00")).strip()
        if color.startswith("#"):
            color = "0x" + color[1:]

        try:
            similarity = float(metadata.get("similarity", 0.15))
        except (TypeError, ValueError):
            similarity = 0.15
        try:
            blend = float(metadata.get("blend", 0.0))
        except (TypeError, ValueError):
            blend = 0.0

        similarity = max(0.01, min(similarity, 1.0))
        blend = max(0.0, min(blend, 1.0))
        expr = f"chromakey={color}:{similarity:.3f}:{blend:.3f}"
        return self._apply_simple_video_filter(input_label, expr)

    def _apply_speed_ramp(
        self, input_label: str, metadata: dict[str, Any], segment: TrackSegment
    ) -> str:
        expr = self._build_speed_ramp_setpts_expr(metadata, segment.source_duration)
        if not expr:
            return input_label
        return self._apply_simple_video_filter(input_label, f"setpts='{expr}/TB'")

    def _build_speed_ramp_setpts_expr(
        self, metadata: dict[str, Any], duration_seconds: float
    ) -> str | None:
        keyframes = metadata.get("keyframes") or []
        if not isinstance(keyframes, list) or not keyframes:
            return None

        points: list[tuple[float, float]] = []
        for item in keyframes:
            if not isinstance(item, dict):
                continue
            raw_t = item.get("time_ms", item.get("time", item.get("t")))
            raw_s = item.get("speed", item.get("value", 1.0))
            if raw_t is None:
                continue
            try:
                t = float(raw_t)
                speed = max(0.01, float(raw_s))
            except (TypeError, ValueError):
                continue

            if duration_seconds > 0 and t > max(10.0, duration_seconds * 2.0):
                t = t / 1000.0
            points.append((max(0.0, t), speed))

        if not points:
            return None

        points.sort(key=lambda p: p[0])
        first_speed = points[0][1]
        if points[0][0] > 0:
            points.insert(0, (0.0, first_speed))

        if duration_seconds > 0:
            last_speed = points[-1][1]
            if points[-1][0] < duration_seconds:
                points.append((duration_seconds, last_speed))
            elif points[-1][0] > duration_seconds:
                points[-1] = (duration_seconds, last_speed)

        deduped: list[tuple[float, float]] = []
        for t, speed in points:
            if deduped and abs(deduped[-1][0] - t) < 1e-6:
                deduped[-1] = (t, speed)
            else:
                deduped.append((t, speed))
        points = deduped

        if len(points) == 1:
            speed = max(0.01, points[0][1])
            return f"T/{speed:.6f}"

        cumulative: list[float] = [0.0]
        for i in range(len(points) - 1):
            start_t, speed = points[i]
            end_t = points[i + 1][0]
            interval = max(0.0, end_t - start_t)
            cumulative.append(cumulative[-1] + (interval / max(0.01, speed)))

        last_start, last_speed = points[-1]
        expr = f"{cumulative[-1]:.6f}+(T-{last_start:.6f})/{max(0.01, last_speed):.6f}"
        for i in range(len(points) - 2, -1, -1):
            start_t, speed = points[i]
            end_t = points[i + 1][0]
            base = cumulative[i]
            expr = (
                f"if(lt(T,{end_t:.6f}),"
                f"{base:.6f}+(T-{start_t:.6f})/{max(0.01, speed):.6f},"
                f"{expr})"
            )

        return expr

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

    def _apply_audio_equalizer(self, input_label: str, metadata: dict[str, Any]) -> str:
        bands = metadata.get("bands")
        filters: list[str] = []
        if isinstance(bands, list):
            for band in bands:
                if not isinstance(band, dict):
                    continue
                freq = band.get("frequency", band.get("freq", 1000))
                gain = band.get("gain", 0)
                width = band.get("width", 1.0)
                try:
                    f = max(20.0, float(freq))
                    g = float(gain)
                    w = max(0.1, float(width))
                except (TypeError, ValueError):
                    continue
                filters.append(f"equalizer=f={f}:width_type=o:width={w}:g={g}")

        if not filters:
            return input_label
        return self._apply_simple_audio_filter(input_label, ",".join(filters))

    def _apply_audio_noise_reduction(
        self, input_label: str, metadata: dict[str, Any]
    ) -> str:
        noise_floor = metadata.get("noise_floor", metadata.get("nf", -25))
        reduction_type = str(metadata.get("type", "white")).lower()
        nt = "w" if reduction_type in {"white", "w"} else "v"
        try:
            nf = float(noise_floor)
        except (TypeError, ValueError):
            nf = -25.0
        expr = f"afftdn=nf={nf}:nt={nt}"
        return self._apply_simple_audio_filter(input_label, expr)

    def _apply_audio_compressor(self, input_label: str, metadata: dict[str, Any]) -> str:
        threshold = metadata.get("threshold", 0.125)
        ratio = metadata.get("ratio", 4)
        attack = metadata.get("attack", 20)
        release = metadata.get("release", 250)
        makeup = metadata.get("makeup", 1)
        expr = (
            f"acompressor=threshold={threshold}:ratio={ratio}:"
            f"attack={attack}:release={release}:makeup={makeup}"
        )
        return self._apply_simple_audio_filter(input_label, expr)

    def _apply_audio_limiter(self, input_label: str, metadata: dict[str, Any]) -> str:
        limit = metadata.get("limit", 0.95)
        attack = metadata.get("attack", 5)
        release = metadata.get("release", 50)
        expr = f"alimiter=limit={limit}:attack={attack}:release={release}"
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
            output_variants=manifest_dict.get("output_variants") or [],
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

        output_path = self._execute_render_command(
            local_asset_map,
            input_streams,
            preset=self.manifest.preset,
            output_path_value=self.manifest.output_path,
            progress_callback=progress_callback,
            progress_start=10,
            progress_end=95,
        )
        output_duration = self._probe_output_duration(output_path)
        if output_duration is not None:
            logger.info("Output duration: %.3fs", output_duration)
            if output_duration <= 0.05:
                raise RenderError("FFmpeg produced zero-duration output")

        _, output_key = self._resolve_output_targets(
            self.manifest.output_path,
            self.manifest.preset,
        )
        output_url = self._upload_output(output_path, output_key)

        variant_outputs = self._render_output_variants(local_asset_map, input_streams)

        logger.info(f"Render complete: {output_path}")

        return {
            "output_path": str(output_path),
            "output_url": output_url,
            "output_size_bytes": output_path.stat().st_size if output_path.exists() else None,
            "variant_outputs": variant_outputs,
        }

    def _execute_render_command(
        self,
        local_asset_map: dict[str, str],
        input_streams: dict[int, set[str]],
        preset: dict[str, Any],
        output_path_value: str,
        progress_callback: Callable[[int, str | None], None] | None = None,
        progress_start: int = 10,
        progress_end: int = 95,
    ) -> Path:
        working_preset = copy.deepcopy(preset)
        ffmpeg_cmd = self._build_ffmpeg_command(
            local_asset_map,
            input_streams,
            preset_override=working_preset,
            output_path_value=output_path_value,
        )

        if progress_callback:
            progress_callback(progress_start, "Built FFmpeg command")
        logger.info("FFmpeg command: %s", self._format_command(ffmpeg_cmd))

        try:
            output_path = self._execute_with_optional_two_pass(
                ffmpeg_cmd,
                working_preset,
                progress_callback,
                progress_start,
                progress_end,
            )
            return Path(output_path)
        except RenderError as exc:
            if not working_preset.get("use_gpu") or not self._is_gpu_encoder_failure(str(exc)):
                raise

            logger.warning(
                "GPU render failed, retrying on CPU encoder. Reason: %s",
                exc,
            )
            fallback_preset = copy.deepcopy(working_preset)
            fallback_preset["use_gpu"] = False
            fallback_cmd = self._build_ffmpeg_command(
                local_asset_map,
                input_streams,
                preset_override=fallback_preset,
                output_path_value=output_path_value,
            )
            if progress_callback:
                progress_callback(progress_start, "Retrying with CPU encoder")
            logger.info("Fallback FFmpeg command: %s", self._format_command(fallback_cmd))
            output_path = self._execute_with_optional_two_pass(
                fallback_cmd,
                fallback_preset,
                progress_callback,
                progress_start,
                progress_end,
            )
            return Path(output_path)

    def _execute_with_optional_two_pass(
        self,
        ffmpeg_cmd: list[str],
        preset: dict[str, Any],
        progress_callback: Callable[[int, str | None], None] | None,
        progress_start: int,
        progress_end: int,
    ) -> str:
        if not self._should_use_two_pass(preset, ffmpeg_cmd):
            return self._execute_ffmpeg(
                ffmpeg_cmd,
                progress_callback,
                progress_start=progress_start,
                progress_end=progress_end,
            )

        passlog_base = str(
            self.temp_dir / f"ffmpeg2pass-{self.manifest.job_id}-{int(time.time())}"
        )
        mid = progress_start + int((progress_end - progress_start) * 0.45)
        pass1_cmd = self._build_first_pass_command(ffmpeg_cmd, passlog_base)
        pass2_cmd = self._build_second_pass_command(ffmpeg_cmd, passlog_base)

        try:
            self._execute_ffmpeg(
                pass1_cmd,
                progress_callback,
                progress_start=progress_start,
                progress_end=mid,
                finalize_message="Completed pass 1",
            )
            return self._execute_ffmpeg(
                pass2_cmd,
                progress_callback,
                progress_start=mid,
                progress_end=progress_end,
            )
        finally:
            self._cleanup_two_pass_logs(passlog_base)

    def _should_use_two_pass(self, preset: dict[str, Any], ffmpeg_cmd: list[str]) -> bool:
        video = dict(preset.get("video", {}) or {})
        codec = str(video.get("codec", "h264")).lower()
        container = self._resolve_container(video, codec)
        video = self._apply_codec_tuned_video_defaults(video, codec, container)
        if not bool(video.get("two_pass", False)):
            return False
        if not video.get("bitrate"):
            logger.warning("two_pass requested but no video bitrate is set; using single pass")
            return False

        encoder = self._extract_video_encoder(ffmpeg_cmd)
        if encoder not in {"libx264", "libx265", "libvpx-vp9"}:
            logger.warning(
                "two_pass requested but encoder '%s' does not support configured two-pass flow; using single pass",
                encoder,
            )
            return False
        return True

    def _extract_video_encoder(self, ffmpeg_cmd: list[str]) -> str | None:
        for index, token in enumerate(ffmpeg_cmd[:-1]):
            if token == "-c:v" and index + 1 < len(ffmpeg_cmd):
                return ffmpeg_cmd[index + 1]
        return None

    def _build_first_pass_command(self, ffmpeg_cmd: list[str], passlog_base: str) -> list[str]:
        base = self._strip_audio_args(ffmpeg_cmd)
        output = "NUL" if os.name == "nt" else "/dev/null"
        return base[:-1] + [
            "-an",
            "-pass",
            "1",
            "-passlogfile",
            passlog_base,
            "-f",
            "null",
            output,
        ]

    def _build_second_pass_command(self, ffmpeg_cmd: list[str], passlog_base: str) -> list[str]:
        return ffmpeg_cmd[:-1] + ["-pass", "2", "-passlogfile", passlog_base, ffmpeg_cmd[-1]]

    def _strip_audio_args(self, ffmpeg_cmd: list[str]) -> list[str]:
        audio_value_flags = {"-c:a", "-b:a", "-ar", "-ac", "-profile:a"}
        stripped: list[str] = []
        i = 0
        last_index = len(ffmpeg_cmd) - 1
        while i < last_index:
            token = ffmpeg_cmd[i]
            if token in audio_value_flags:
                i += 2
                continue
            if token == "-movflags":
                i += 2
                continue
            if token == "-map" and i + 1 < last_index:
                map_value = ffmpeg_cmd[i + 1]
                map_lower = map_value.lower()
                if map_lower.startswith("[a") or map_lower.endswith(":a") or map_lower == "0:a":
                    i += 2
                    continue
                stripped.extend([token, map_value])
                i += 2
                continue
            stripped.append(token)
            i += 1

        stripped.append(ffmpeg_cmd[-1])
        return stripped

    def _cleanup_two_pass_logs(self, passlog_base: str) -> None:
        base_path = Path(passlog_base)
        parent = base_path.parent
        prefix = base_path.name
        if not parent.exists():
            return
        for path in parent.glob(f"{prefix}*"):
            if path.is_file():
                try:
                    path.unlink()
                except OSError:
                    pass

    def _is_gpu_encoder_failure(self, error_text: str) -> bool:
        text = error_text.lower()
        keywords = [
            "nvenc",
            "amf",
            "videotoolbox",
            "no capable devices found",
            "cannot load libcuda",
            "cuda error",
            "device not available",
            "hardware device",
            "unsupported device",
        ]
        return any(keyword in text for keyword in keywords)

    def _render_output_variants(
        self,
        local_asset_map: dict[str, str],
        input_streams: dict[int, set[str]],
    ) -> list[dict[str, Any]]:
        variants = self.manifest.output_variants or []
        if not variants:
            return []

        results: list[dict[str, Any]] = []
        for index, variant in enumerate(variants):
            if not isinstance(variant, dict):
                continue
            variant_preset = self._merge_variant_preset(self.manifest.preset, variant)
            variant_output_path = self._derive_variant_output_path(
                self.manifest.output_path,
                variant,
                index,
            )
            logger.info(
                "Rendering output variant %d/%d -> %s",
                index + 1,
                len(variants),
                variant_output_path,
            )
            rendered_path = self._execute_render_command(
                local_asset_map,
                input_streams,
                preset=variant_preset,
                output_path_value=variant_output_path,
                progress_callback=None,
                progress_start=0,
                progress_end=100,
            )
            _, output_key = self._resolve_output_targets(variant_output_path, variant_preset)
            output_url = self._upload_output(rendered_path, output_key)
            results.append(
                {
                    "output_path": str(rendered_path),
                    "output_url": output_url,
                    "output_size_bytes": rendered_path.stat().st_size if rendered_path.exists() else None,
                    "preset": variant_preset,
                }
            )
        return results

    def _merge_variant_preset(
        self,
        base_preset: dict[str, Any],
        variant: dict[str, Any],
    ) -> dict[str, Any]:
        merged = copy.deepcopy(base_preset)
        merged.setdefault("video", {})
        merged.setdefault("audio", {})

        variant_video = variant.get("video")
        if isinstance(variant_video, dict):
            merged["video"].update({k: v for k, v in variant_video.items() if v is not None})
        else:
            reserved = {"audio", "label", "name", "use_gpu", "gpu_backend"}
            merged["video"].update(
                {
                    k: v
                    for k, v in variant.items()
                    if k not in reserved and v is not None
                }
            )

        variant_audio = variant.get("audio")
        if isinstance(variant_audio, dict):
            merged["audio"].update({k: v for k, v in variant_audio.items() if v is not None})

        if "use_gpu" in variant:
            merged["use_gpu"] = bool(variant.get("use_gpu"))
        if "gpu_backend" in variant:
            merged["gpu_backend"] = variant.get("gpu_backend")

        return merged

    def _derive_variant_output_path(
        self,
        base_output_path: str,
        variant: dict[str, Any],
        index: int,
    ) -> str:
        base = Path(base_output_path)
        label = str(variant.get("label") or variant.get("name") or "").strip()
        if not label:
            video = variant.get("video") if isinstance(variant.get("video"), dict) else variant
            height = video.get("height") if isinstance(video, dict) else None
            width = video.get("width") if isinstance(video, dict) else None
            if height:
                label = f"{height}p"
            elif width:
                label = f"{width}w"
            else:
                label = f"variant{index + 1}"

        safe_label = re.sub(r"[^A-Za-z0-9_-]", "_", label)
        suffix = base.suffix or ".mp4"
        return str(base.with_name(f"{base.stem}_{safe_label}{suffix}"))


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

    def _upload_output(
        self,
        output_path: Path,
        output_key: str | None = None,
    ) -> str | None:
        if not output_path.exists():
            raise RenderError(f"Render output not found: {output_path}")

        output_bucket = self.manifest.output_bucket
        if not output_bucket or output_bucket == "local":
            logger.info("Skipping GCS upload for local output bucket")
            return None

        upload_target = output_key or self.manifest.output_path
        if Path(upload_target).is_absolute():
            logger.info("Skipping GCS upload for absolute output path")
            return None

        bucket_name, blob_path = self._parse_gcs_path(
            upload_target, output_bucket
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
        preset_override: dict[str, Any] | None = None,
        output_path_value: str | None = None,
    ) -> list[str]:
        timeline = self.manifest.timeline_snapshot
        preset = preset_override or self.manifest.preset
        output_value = output_path_value or self.manifest.output_path
        output_path, _ = self._resolve_output_targets(output_value, preset)


        cmd = [self._ffmpeg_bin, "-y"]

        inputs, filter_complex, maps = self._build_filter_graph(
            timeline, asset_map, input_streams, preset
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
        preset: dict[str, Any],
    ) -> tuple[list[InputSpec], str, list[str]]:
        builder = TimelineToFFmpeg(
            timeline,
            asset_map,
            preset,
            input_streams,
            temp_dir=self.temp_dir,
            job_id=self.manifest.job_id,
        )
        inputs, filter_complex, maps = builder.build()

        if not filter_complex and inputs:
            maps = ["0:v", "0:a"]

        return inputs, filter_complex, maps

    def _resolve_output_targets(
        self,
        output_path_value: str,
        preset: dict[str, Any],
    ) -> tuple[Path, str | None]:
        video = preset.get("video", {})
        codec = str(video.get("codec", "h264")).lower()
        container = self._resolve_container(video, codec)
        ext = f".{container}"

        output_path = Path(output_path_value)
        if output_path.suffix.lower() != ext:
            output_path = output_path.with_suffix(ext)

        if output_path.is_absolute():
            output_path.parent.mkdir(parents=True, exist_ok=True)
            return output_path, None

        output_path = self.outputs_dir / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        upload_key = str(output_path.relative_to(self.outputs_dir)).replace("\\", "/")
        return output_path, upload_key

    def _resolve_container(self, video: dict[str, Any], codec: str) -> str:
        requested = str(video.get("container", "")).strip().lower()
        valid = {"mp4", "mov", "mkv", "webm"}
        container = requested if requested in valid else ""

        if codec == "prores":
            if container not in {"mov", "mkv"}:
                return "mov"
            return container
        if codec == "vp9":
            if container not in {"webm", "mkv"}:
                return "webm"
            return container
        if codec == "av1":
            if container in {"webm", "mkv", "mp4"}:
                return container
            return "mkv"
        if codec in {"h264", "h265"} and container == "webm":
            return "mp4"
        return container or "mp4"

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
        options: list[str] = []
        video = dict(preset.get("video", {}) or {})
        audio = dict(preset.get("audio", {}) or {})
        use_gpu = bool(preset.get("use_gpu", False))

        codec = str(video.get("codec", "h264")).lower()
        container = self._resolve_container(video, codec)
        video = self._apply_codec_tuned_video_defaults(video, codec, container)
        gop_size = self._resolve_gop_size(video)
        video_encoder = ""
        selected_backend: str | None = None

        if use_gpu and codec in {"h264", "h265"}:
            selected_backend, video_encoder = self._select_gpu_backend_and_encoder(
                preset,
                codec,
            )
            video_encoder = video_encoder or ""
            if video_encoder:
                options.extend(["-c:v", video_encoder])
            else:
                logger.warning(
                    "GPU encoding requested, but no compatible %s hardware encoder is available. Using CPU encoder.",
                    codec,
                )
                use_gpu = False
        elif use_gpu and codec not in {"h264", "h265"}:
            logger.warning(
                "GPU encoding requested for codec '%s', but this codec uses CPU encoding. Falling back to CPU.",
                codec,
            )
            use_gpu = False

        if not use_gpu:
            video_encoder = self._cpu_encoder_for_codec(codec)
            if not video_encoder:
                raise RenderError(f"Unsupported video codec: {codec}")
            options.extend(["-c:v", video_encoder])

        if video_encoder:
            logger.info("Using video encoder: %s", video_encoder)
        if selected_backend:
            logger.info("Using GPU backend: %s", selected_backend)

        bitrate = video.get("bitrate")
        crf = video.get("crf", 23)
        if bitrate:
            bitrate_value = str(bitrate)
            options.extend(["-b:v", bitrate_value])
            if not use_gpu and video_encoder in {"libx264", "libx265"}:
                buffer = self._double_bitrate(bitrate_value)
                if buffer:
                    options.extend(["-maxrate", bitrate_value, "-bufsize", buffer])
        elif crf is not None:
            if use_gpu and video_encoder.endswith("_nvenc"):
                options.extend(["-cq", str(crf)])
            elif not use_gpu and video_encoder == "libvpx-vp9":
                options.extend(["-crf", str(crf), "-b:v", "0"])
            elif not use_gpu and video_encoder != "prores_ks":
                options.extend(["-crf", str(crf)])

        enc_preset = str(video.get("preset", "medium"))
        if use_gpu and video_encoder.endswith("_nvenc"):
            options.extend(["-preset", self._map_nvenc_preset(enc_preset)])
        elif video_encoder == "libsvtav1":
            options.extend(["-preset", str(self._map_svtav1_preset(enc_preset))])
        elif video_encoder in {"libx264", "libx265"}:
            options.extend(["-preset", enc_preset])
        elif video_encoder == "libvpx-vp9":
            options.extend(["-cpu-used", str(self._map_vp9_cpu_used(enc_preset))])

        if video_encoder == "prores_ks":
            profile = self._normalize_prores_profile(video.get("prores_profile", "hq"))
            options.extend(["-profile:v", profile])
            if str(video.get("vendor", "apl0")):
                options.extend(["-vendor", str(video.get("vendor", "apl0"))])
        elif video_encoder == "libvpx-vp9":
            options.extend(
                [
                    "-quality",
                    str(video.get("vp9_quality", "good")),
                    "-row-mt",
                    str(video.get("vp9_row_mt", 1)),
                    "-tile-columns",
                    str(video.get("vp9_tile_columns", 2)),
                    "-frame-parallel",
                    str(video.get("vp9_frame_parallel", 1)),
                    "-auto-alt-ref",
                    str(video.get("vp9_auto_alt_ref", 1)),
                    "-lag-in-frames",
                    str(video.get("vp9_lag_in_frames", 25)),
                    "-g",
                    str(gop_size),
                ]
            )
        elif video_encoder == "libsvtav1":
            options.extend(
                [
                    "-svtav1-params",
                    str(
                        video.get(
                            "svtav1_params",
                            "tune=0:enable-qm=1:qm-min=0:qm-max=8",
                        )
                    ),
                ]
            )

        if video_encoder == "libx264":
            options.extend(["-profile:v", str(video.get("h264_profile", "high"))])
            options.extend(["-g", str(gop_size)])
        if video_encoder == "libx265":
            x265_params = str(video.get("x265_params", "aq-mode=3:aq-strength=1.0:qcomp=0.7"))
            options.extend(["-x265-params", x265_params])
            options.extend(["-g", str(gop_size)])
            if container in {"mp4", "mov"}:
                options.extend(["-tag:v", "hvc1"])
        if use_gpu and video_encoder.endswith("_nvenc"):
            options.extend(["-g", str(gop_size)])

        default_pix_fmt = "yuv420p10le" if codec == "h265" else "yuv420p"
        pix_fmt = str(video.get("pixel_format") or default_pix_fmt)
        options.extend(["-pix_fmt", pix_fmt])

        color_space = video.get("color_space", "bt709")
        color_primaries = video.get("color_primaries", "bt709")
        color_trc = video.get("color_trc", "bt709")
        if color_space:
            options.extend(["-colorspace", str(color_space)])
        if color_primaries:
            options.extend(["-color_primaries", str(color_primaries)])
        if color_trc:
            options.extend(["-color_trc", str(color_trc)])

        audio_codec = str(audio.get("codec", "aac")).lower()
        if container == "webm" and audio_codec not in {"opus", "vorbis"}:
            logger.warning(
                "Container webm is most compatible with Opus audio. Overriding requested codec '%s' to opus.",
                audio_codec,
            )
            audio_codec = "opus"

        if audio_codec == "aac":
            options.extend(["-c:a", "aac"])
        elif audio_codec == "mp3":
            options.extend(["-c:a", "libmp3lame"])
        elif audio_codec == "opus":
            options.extend(["-c:a", "libopus", "-vbr", "on", "-compression_level", "10"])
        else:
            logger.warning("Unsupported audio codec '%s'. Falling back to AAC.", audio_codec)
            options.extend(["-c:a", "aac"])

        audio_bitrate = str(audio.get("bitrate") or ("160k" if audio_codec == "opus" else "192k"))
        sample_rate = int(audio.get("sample_rate", 48000) or 48000)
        channels = int(audio.get("channels", 2) or 2)
        options.extend(["-b:a", audio_bitrate, "-ar", str(sample_rate), "-ac", str(channels)])

        if audio_codec == "aac":
            options.extend(["-profile:a", str(audio.get("aac_profile", "aac_low"))])

        if container in {"mp4", "mov"}:
            options.extend(["-movflags", "+faststart"])

        return options

    def _apply_codec_tuned_video_defaults(
        self,
        video: dict[str, Any],
        codec: str,
        container: str,
    ) -> dict[str, Any]:
        tuned = dict(video)

        def set_if_missing(key: str, value: Any) -> None:
            current = tuned.get(key)
            if current is None:
                tuned[key] = value
                return
            if isinstance(current, str) and not current.strip():
                tuned[key] = value

        if codec == "h264":
            set_if_missing("pixel_format", "yuv420p")
            set_if_missing("preset", "medium")
            set_if_missing("crf", 21)
            set_if_missing("h264_profile", "high")
        elif codec == "h265":
            set_if_missing("pixel_format", "yuv420p10le")
            set_if_missing("preset", "slow")
            set_if_missing("crf", 19)
            set_if_missing("x265_params", "aq-mode=3:aq-strength=1.0:qcomp=0.7")
        elif codec == "prores":
            set_if_missing("container", "mov")
            set_if_missing("pixel_format", "yuv422p10le")
            set_if_missing("prores_profile", "hq")
            set_if_missing("vendor", "apl0")
            set_if_missing("bitrate", "110M")
            tuned["crf"] = None
            tuned["two_pass"] = False
        elif codec == "vp9":
            set_if_missing("container", "webm")
            set_if_missing("pixel_format", "yuv420p")
            set_if_missing("preset", "medium")
            set_if_missing("crf", 30)
            set_if_missing("bitrate", "8M")
            set_if_missing("vp9_quality", "good")
            set_if_missing("vp9_row_mt", 1)
            set_if_missing("vp9_tile_columns", 2)
            set_if_missing("vp9_frame_parallel", 1)
            set_if_missing("vp9_auto_alt_ref", 1)
            set_if_missing("vp9_lag_in_frames", 25)
            if "two_pass" not in tuned and tuned.get("bitrate"):
                tuned["two_pass"] = True
        elif codec == "av1":
            set_if_missing("container", "mkv")
            set_if_missing("pixel_format", "yuv420p10le")
            set_if_missing("preset", "medium")
            set_if_missing("crf", 29)
            set_if_missing("bitrate", "6M")
            set_if_missing("svtav1_params", "tune=0:enable-qm=1:qm-min=0:qm-max=8")

        tuned["container"] = tuned.get("container") or container
        return tuned

    def _normalize_prores_profile(self, value: Any) -> str:
        mapping = {
            "proxy": "0",
            "lt": "1",
            "standard": "2",
            "hq": "3",
            "4444": "4",
            "4444xq": "5",
        }
        text = str(value).strip().lower()
        if text in mapping:
            return mapping[text]
        if text in {"0", "1", "2", "3", "4", "5"}:
            return text
        return "3"

    def _map_vp9_cpu_used(self, preset: str) -> int:
        mapping = {
            "ultrafast": 8,
            "superfast": 7,
            "veryfast": 6,
            "faster": 5,
            "fast": 4,
            "medium": 3,
            "slow": 2,
            "slower": 1,
            "veryslow": 0,
        }
        return mapping.get(preset, 3)

    def _cpu_encoder_for_codec(self, codec: str) -> str | None:
        mapping = {
            "h264": "libx264",
            "h265": "libx265",
            "prores": "prores_ks",
            "vp9": "libvpx-vp9",
            "av1": "libsvtav1",
        }
        return mapping.get(codec)

    def _double_bitrate(self, bitrate: str) -> str | None:
        match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)([kKmMgG])\s*", bitrate)
        if not match:
            return None
        value = float(match.group(1)) * 2
        unit = match.group(2)
        if value.is_integer():
            value_str = str(int(value))
        else:
            value_str = f"{value:.2f}".rstrip("0").rstrip(".")
        return f"{value_str}{unit}"

    def _map_nvenc_preset(self, preset: str) -> str:
        mapping = {
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
        return mapping.get(preset, "medium")

    def _map_svtav1_preset(self, preset: str) -> int:
        mapping = {
            "ultrafast": 12,
            "superfast": 11,
            "veryfast": 10,
            "faster": 9,
            "fast": 8,
            "medium": 6,
            "slow": 4,
            "slower": 3,
            "veryslow": 2,
        }
        return mapping.get(preset, 6)

    def _resolve_gop_size(self, video: dict[str, Any]) -> int:
        raw_gop = video.get("gop_size")
        if raw_gop is not None:
            try:
                return max(1, int(raw_gop))
            except (TypeError, ValueError):
                pass
        fps = self._preset_framerate(video)
        return max(24, int(round(fps * 2)))

    def _preset_framerate(self, video: dict[str, Any]) -> float:
        raw = video.get("framerate")
        if raw is not None:
            try:
                value = float(raw)
                if value > 0:
                    return value
            except (TypeError, ValueError):
                pass
        timeline_rate = self.manifest.timeline_snapshot.get("metadata", {}).get(
            "default_rate", 24.0
        )
        try:
            value = float(timeline_rate)
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass
        return 24.0

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
        progress_start: int = 10,
        progress_end: int = 95,
        finalize_message: str | None = "Finalizing output",
    ) -> str:
        output_path = cmd[-1]

        cmd_with_progress = cmd[:-1] + ["-progress", "pipe:1", cmd[-1]]

        logger.info("Executing FFmpeg...")
        logger.debug(f"Command: {' '.join(cmd_with_progress)}")

        timeout_seconds_raw = os.environ.get("FFMPEG_TIMEOUT_SECONDS", "7200")
        try:
            timeout_seconds = max(60, int(timeout_seconds_raw))
        except ValueError:
            timeout_seconds = 7200

        try:
            process = subprocess.Popen(
                cmd_with_progress,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            duration = None
            last_progress = progress_start
            output_tail: list[str] = []
            timed_out = False

            def _kill_process_on_timeout() -> None:
                nonlocal timed_out
                timed_out = True
                process.kill()

            timer = threading.Timer(timeout_seconds, _kill_process_on_timeout)
            timer.daemon = True
            timer.start()

            if process.stdout is None:
                raise RenderError("FFmpeg did not provide a stdout stream")

            try:
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
                                progress_span = max(1, progress_end - progress_start)
                                pct = min(
                                    progress_end,
                                    progress_start + int((time_sec / duration) * progress_span),
                                )
                                if pct > last_progress and progress_callback:
                                    progress_callback(pct, None)
                                    last_progress = pct
                        except (ValueError, IndexError):
                            pass

                process.wait()
            finally:
                timer.cancel()

            if timed_out:
                tail_text = "\n".join(output_tail[-40:])
                raise RenderError(
                    f"FFmpeg timed out after {timeout_seconds}s. Output tail:\n{tail_text}"
                )

            if process.returncode != 0:
                tail_text = "\n".join(output_tail[-40:])
                raise RenderError(
                    f"FFmpeg failed (code {process.returncode}). Output:\n{tail_text}"
                )
            if output_tail:
                logger.info("FFmpeg output (tail): %s", "\n".join(output_tail[-20:]))

            if progress_callback and finalize_message:
                progress_callback(progress_end, finalize_message)

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
