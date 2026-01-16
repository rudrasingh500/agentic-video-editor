from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from models.timeline_models import (
    Clip,
    ExternalReference,
    FreezeFrame,
    Gap,
    GeneratorReference,
    LinearTimeWarp,
    MissingReference,
    Stack,
    Timeline,
    Track,
    Transition,
    TransitionType,
)
from models.render_models import RenderPreset, VideoCodec

logger = logging.getLogger(__name__)


@dataclass
class InputFile:
    index: int
    asset_id: str
    file_path: str
    duration: float | None = None


@dataclass
class FilterNode:
    name: str
    filter_expr: str


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


@dataclass
class TransitionInfo:
    position: int
    transition_type: TransitionType
    duration: float
    in_offset: float
    out_offset: float


@dataclass
class FFmpegCommand:
    inputs: list[str]
    filter_complex: str
    output_maps: list[str]
    output_options: list[str]
    output_file: str


class TimelineToFFmpeg:
    def __init__(
        self,
        timeline: Timeline,
        asset_map: dict[str, str],
        preset: RenderPreset,
        output_path: str,
    ):
        self.timeline = timeline
        self.asset_map = asset_map
        self.preset = preset
        self.output_path = output_path

        self._inputs: list[InputFile] = []
        self._input_index_map: dict[str, int] = {}
        self._filter_counter = 0
        self._video_filters: list[str] = []
        self._audio_filters: list[str] = []

    def build(self) -> FFmpegCommand:
        self._inputs = []
        self._input_index_map = {}
        self._filter_counter = 0
        self._video_filters = []
        self._audio_filters = []

        self._collect_inputs()

        video_out = self._build_video_graph()
        audio_out = self._build_audio_graph()

        filter_complex = self._combine_filters()

        output_options = self._build_output_options()

        output_maps = []
        if video_out:
            output_maps.append(f"[{video_out}]")
        if audio_out:
            output_maps.append(f"[{audio_out}]")

        return FFmpegCommand(
            inputs=[f"-i {inp.file_path}" for inp in self._inputs],
            filter_complex=filter_complex,
            output_maps=output_maps,
            output_options=output_options,
            output_file=self.output_path,
        )

    def build_command_string(self) -> str:
        cmd = self.build()

        parts = ["ffmpeg", "-y"]

        for inp in cmd.inputs:
            parts.append(inp)

        if cmd.filter_complex:
            filter_escaped = cmd.filter_complex.replace("'", "'\\''")
            parts.append(f"-filter_complex '{filter_escaped}'")

        for m in cmd.output_maps:
            parts.append(f"-map {m}")

        parts.extend(cmd.output_options)

        parts.append(f'"{cmd.output_file}"')

        return " ".join(parts)

    def _collect_inputs(self) -> None:
        clips = self.timeline.find_clips()

        for clip in clips:
            if isinstance(clip.media_reference, ExternalReference):
                asset_id = str(clip.media_reference.asset_id)
                if asset_id not in self._input_index_map:
                    if asset_id in self.asset_map:
                        input_file = InputFile(
                            index=len(self._inputs),
                            asset_id=asset_id,
                            file_path=self.asset_map[asset_id],
                        )
                        self._inputs.append(input_file)
                        self._input_index_map[asset_id] = input_file.index
                    else:
                        logger.warning(f"Asset {asset_id} not found in asset_map")

    def _build_video_graph(self) -> str | None:
        video_tracks = self.timeline.video_tracks
        if not video_tracks:
            return None

        track_outputs: list[str] = []

        for track_idx, track in enumerate(video_tracks):
            track_out = self._process_video_track(track, track_idx)
            if track_out:
                track_outputs.append(track_out)

        if not track_outputs:
            return None

        if len(track_outputs) == 1:
            return track_outputs[0]
        else:
            return self._overlay_video_tracks(track_outputs)

    def _build_audio_graph(self) -> str | None:
        audio_tracks = self.timeline.audio_tracks
        if not audio_tracks:
            video_tracks = self.timeline.video_tracks
            if video_tracks:
                return self._extract_audio_from_video()
            return None

        track_outputs: list[str] = []

        for track_idx, track in enumerate(audio_tracks):
            track_out = self._process_audio_track(track, track_idx)
            if track_out:
                track_outputs.append(track_out)

        if not track_outputs:
            return None

        if len(track_outputs) == 1:
            return track_outputs[0]
        else:
            return self._mix_audio_tracks(track_outputs)

    def _process_video_track(self, track: Track, track_idx: int) -> str | None:
        segments = self._extract_track_segments(track)
        transitions = self._extract_transitions(track)

        if not segments:
            return None

        segment_outputs: list[str] = []

        for seg_idx, segment in enumerate(segments):
            seg_out = self._process_video_segment(segment, track_idx, seg_idx)
            if seg_out:
                segment_outputs.append(seg_out)

        if not segment_outputs:
            return None

        if transitions and len(segment_outputs) > 1:
            return self._apply_video_transitions(segment_outputs, transitions)
        elif len(segment_outputs) == 1:
            return segment_outputs[0]
        else:
            return self._concat_video_segments(segment_outputs)

    def _process_audio_track(self, track: Track, track_idx: int) -> str | None:
        segments = self._extract_track_segments(track)
        transitions = self._extract_transitions(track)

        if not segments:
            return None

        segment_outputs: list[str] = []

        for seg_idx, segment in enumerate(segments):
            seg_out = self._process_audio_segment(segment, track_idx, seg_idx)
            if seg_out:
                segment_outputs.append(seg_out)

        if not segment_outputs:
            return None

        if transitions and len(segment_outputs) > 1:
            return self._apply_audio_transitions(segment_outputs, transitions)
        elif len(segment_outputs) == 1:
            return segment_outputs[0]
        else:
            return self._concat_audio_segments(segment_outputs)

    def _extract_track_segments(self, track: Track) -> list[TrackSegment]:
        segments: list[TrackSegment] = []
        current_time = 0.0

        for child in track.children:
            if isinstance(child, Transition):
                continue

            elif isinstance(child, Clip):
                segment = self._clip_to_segment(child, current_time)
                segments.append(segment)
                current_time += segment.duration

            elif isinstance(child, Gap):
                duration = child.source_range.duration.to_seconds()
                segments.append(
                    TrackSegment(
                        start_time=current_time,
                        duration=duration,
                        source_start=0,
                        source_duration=duration,
                        input_index=None,
                        is_gap=True,
                    )
                )
                current_time += duration

            elif isinstance(child, Stack):
                stack_duration = child.duration().to_seconds()
                segments.append(
                    TrackSegment(
                        start_time=current_time,
                        duration=stack_duration,
                        source_start=0,
                        source_duration=stack_duration,
                        input_index=None,
                        is_gap=True,
                    )
                )
                current_time += stack_duration

        return segments

    def _clip_to_segment(self, clip: Clip, timeline_start: float) -> TrackSegment:
        source_start = clip.source_range.start_time.to_seconds()
        source_duration = clip.source_range.duration.to_seconds()

        input_index: int | None = None
        is_generator = False
        generator_params: dict[str, Any] = {}
        speed_factor = 1.0
        is_freeze = False

        if isinstance(clip.media_reference, ExternalReference):
            asset_id = str(clip.media_reference.asset_id)
            input_index = self._input_index_map.get(asset_id)
        elif isinstance(clip.media_reference, GeneratorReference):
            is_generator = True
            generator_params = {
                "kind": clip.media_reference.generator_kind,
                "params": clip.media_reference.parameters,
            }
        elif isinstance(clip.media_reference, MissingReference):
            return TrackSegment(
                start_time=timeline_start,
                duration=source_duration,
                source_start=0,
                source_duration=source_duration,
                input_index=None,
                is_gap=True,
            )

        effects_data: list[dict[str, Any]] = []
        for effect in clip.effects:
            if isinstance(effect, LinearTimeWarp):
                speed_factor = effect.time_scalar
                effects_data.append({"type": "speed", "factor": speed_factor})
            elif isinstance(effect, FreezeFrame):
                is_freeze = True
                effects_data.append({"type": "freeze"})
            else:
                effects_data.append(
                    {
                        "type": "generic",
                        "name": effect.effect_name,
                        "metadata": effect.metadata,
                    }
                )

        timeline_duration = (
            source_duration / speed_factor if speed_factor != 0 else source_duration
        )

        return TrackSegment(
            start_time=timeline_start,
            duration=timeline_duration,
            source_start=source_start,
            source_duration=source_duration,
            input_index=input_index,
            is_gap=False,
            is_generator=is_generator,
            generator_params=generator_params,
            speed_factor=speed_factor,
            is_freeze=is_freeze,
            effects=effects_data,
        )

    def _extract_transitions(self, track: Track) -> list[TransitionInfo]:
        transitions: list[TransitionInfo] = []
        position = 0

        for child in track.children:
            if isinstance(child, Transition):
                transitions.append(
                    TransitionInfo(
                        position=position,
                        transition_type=child.transition_type,
                        duration=child.duration.to_seconds(),
                        in_offset=child.in_offset.to_seconds(),
                        out_offset=child.out_offset.to_seconds(),
                    )
                )
            elif not isinstance(child, Transition):
                position += 1

        return transitions

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

        trim_filter = (
            f"trim=start={segment.source_start}:duration={segment.source_duration}"
        )
        filters.append(trim_filter)

        filters.append("setpts=PTS-STARTPTS")

        if segment.is_freeze:
            filters.append("select='eq(n,0)',loop=loop=-1:size=1")
        elif segment.speed_factor != 1.0:
            pts_factor = 1.0 / segment.speed_factor
            filters.append(f"setpts={pts_factor}*PTS")

        if self.preset.video.width and self.preset.video.height:
            filters.append(
                f"scale={self.preset.video.width}:{self.preset.video.height}:force_original_aspect_ratio=decrease,"
                f"pad={self.preset.video.width}:{self.preset.video.height}:(ow-iw)/2:(oh-ih)/2"
            )

        filter_chain = ",".join(filters)
        self._video_filters.append(f"[{input_label}]{filter_chain}[{label}]")

        return label

    def _process_audio_segment(
        self, segment: TrackSegment, track_idx: int, seg_idx: int
    ) -> str | None:
        label = f"a{track_idx}_{seg_idx}"

        if segment.is_gap or segment.is_generator:
            return self._generate_gap_audio(segment, label)

        if segment.input_index is None:
            return None

        filters: list[str] = []
        input_label = f"{segment.input_index}:a"

        trim_filter = (
            f"atrim=start={segment.source_start}:duration={segment.source_duration}"
        )
        filters.append(trim_filter)

        filters.append("asetpts=PTS-STARTPTS")

        if segment.is_freeze:
            pass
        elif segment.speed_factor != 1.0:
            tempo = segment.speed_factor
            tempo_filters = self._build_atempo_chain(tempo)
            filters.extend(tempo_filters)

        filter_chain = ",".join(filters)
        self._audio_filters.append(f"[{input_label}]{filter_chain}[{label}]")

        return label

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

        return filters if filters else []

    def _generate_gap_video(self, segment: TrackSegment, label: str) -> str:
        width = self.preset.video.width or 1920
        height = self.preset.video.height or 1080
        framerate = self.preset.video.framerate or 24

        self._video_filters.append(
            f"color=c=black:s={width}x{height}:d={segment.duration}:r={framerate}[{label}]"
        )
        return label

    def _generate_gap_audio(self, segment: TrackSegment, label: str) -> str:
        sample_rate = self.preset.audio.sample_rate
        channels = self.preset.audio.channels

        self._audio_filters.append(
            f"anullsrc=r={sample_rate}:cl={'stereo' if channels == 2 else 'mono'},"
            f"atrim=duration={segment.duration}[{label}]"
        )
        return label

    def _generate_generator_video(self, segment: TrackSegment, label: str) -> str:
        kind = segment.generator_params.get("kind", "SolidColor")
        params = segment.generator_params.get("params", {})

        width = self.preset.video.width or 1920
        height = self.preset.video.height or 1080
        framerate = self.preset.video.framerate or 24

        if kind == "SolidColor":
            color = params.get("color", "black")
            self._video_filters.append(
                f"color=c={color}:s={width}x{height}:d={segment.duration}:r={framerate}[{label}]"
            )
        elif kind == "Bars":
            self._video_filters.append(
                f"smptebars=s={width}x{height}:d={segment.duration}:r={framerate}[{label}]"
            )
        else:
            self._video_filters.append(
                f"color=c=black:s={width}x{height}:d={segment.duration}:r={framerate}[{label}]"
            )

        return label

    def _apply_video_transitions(
        self, segments: list[str], transitions: list[TransitionInfo]
    ) -> str:
        if not transitions:
            return self._concat_video_segments(segments)

        result = segments[0]
        transition_idx = 0

        for i in range(1, len(segments)):
            out_label = f"vtrans_{self._filter_counter}"
            self._filter_counter += 1

            trans = None
            if transition_idx < len(transitions):
                if transitions[transition_idx].position == i:
                    trans = transitions[transition_idx]
                    transition_idx += 1

            if trans:
                trans_type = self._map_transition_type(trans.transition_type)
                offset = max(0, trans.duration / 2)

                self._video_filters.append(
                    f"[{result}][{segments[i]}]xfade=transition={trans_type}:"
                    f"duration={trans.duration}:offset={offset}[{out_label}]"
                )
            else:
                self._video_filters.append(
                    f"[{result}][{segments[i]}]concat=n=2:v=1:a=0[{out_label}]"
                )

            result = out_label

        return result

    def _apply_audio_transitions(
        self, segments: list[str], transitions: list[TransitionInfo]
    ) -> str:
        if not transitions:
            return self._concat_audio_segments(segments)

        result = segments[0]
        transition_idx = 0

        for i in range(1, len(segments)):
            out_label = f"atrans_{self._filter_counter}"
            self._filter_counter += 1

            trans = None
            if transition_idx < len(transitions):
                if transitions[transition_idx].position == i:
                    trans = transitions[transition_idx]
                    transition_idx += 1

            if trans:
                self._audio_filters.append(
                    f"[{result}][{segments[i]}]acrossfade=d={trans.duration}[{out_label}]"
                )
            else:
                self._audio_filters.append(
                    f"[{result}][{segments[i]}]concat=n=2:v=0:a=1[{out_label}]"
                )

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
        video_tracks = self.timeline.video_tracks
        if not video_tracks:
            return None

        track = video_tracks[0]
        segments = self._extract_track_segments(track)

        audio_outputs: list[str] = []
        for seg_idx, segment in enumerate(segments):
            if segment.input_index is not None:
                seg_out = self._process_audio_segment(segment, 0, seg_idx)
                if seg_out:
                    audio_outputs.append(seg_out)

        if not audio_outputs:
            return None

        if len(audio_outputs) == 1:
            return audio_outputs[0]

        return self._concat_audio_segments(audio_outputs)

    def _map_transition_type(self, trans_type: TransitionType) -> str:
        mapping = {
            TransitionType.SMPTE_DISSOLVE: "dissolve",
            TransitionType.FADE_IN: "fade",
            TransitionType.FADE_OUT: "fade",
            TransitionType.WIPE: "wipeleft",
            TransitionType.SLIDE: "slideleft",
            TransitionType.CUSTOM: "dissolve",
        }
        return mapping.get(trans_type, "dissolve")

    def _combine_filters(self) -> str:
        all_filters = self._video_filters + self._audio_filters
        return ";".join(all_filters)

    def _build_output_options(self) -> list[str]:
        options: list[str] = []

        if self.preset.use_gpu:
            if self.preset.video.codec == VideoCodec.H264:
                options.extend(["-c:v", "h264_nvenc"])
            elif self.preset.video.codec == VideoCodec.H265:
                options.extend(["-c:v", "hevc_nvenc"])
        else:
            if self.preset.video.codec == VideoCodec.H264:
                options.extend(["-c:v", "libx264"])
            elif self.preset.video.codec == VideoCodec.H265:
                options.extend(["-c:v", "libx265"])

        if self.preset.video.crf is not None:
            if self.preset.use_gpu:
                options.extend(["-cq", str(self.preset.video.crf)])
            else:
                options.extend(["-crf", str(self.preset.video.crf)])

        if self.preset.video.bitrate:
            options.extend(["-b:v", self.preset.video.bitrate])

        if self.preset.use_gpu:
            nvenc_preset = self._map_nvenc_preset(self.preset.video.preset)
            options.extend(["-preset", nvenc_preset])
        else:
            options.extend(["-preset", self.preset.video.preset])

        options.extend(["-pix_fmt", self.preset.video.pixel_format])

        if self.preset.audio.codec.value == "aac":
            options.extend(["-c:a", "aac"])
        elif self.preset.audio.codec.value == "mp3":
            options.extend(["-c:a", "libmp3lame"])

        options.extend(["-b:a", self.preset.audio.bitrate])
        options.extend(["-ar", str(self.preset.audio.sample_rate)])
        options.extend(["-ac", str(self.preset.audio.channels)])

        options.extend(["-movflags", "+faststart"])

        return options

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


def build_render_command(
    timeline_dict: dict[str, Any],
    asset_map: dict[str, str],
    preset: RenderPreset,
    output_path: str,
) -> str:
    timeline = Timeline.model_validate(timeline_dict)
    converter = TimelineToFFmpeg(timeline, asset_map, preset, output_path)
    return converter.build_command_string()


def estimate_render_duration(timeline: Timeline, preset: RenderPreset) -> float:
    timeline_duration = timeline.duration.to_seconds()

    if preset.use_gpu:
        multiplier = 0.1 if preset.quality.value in ["draft", "standard"] else 0.2
    else:
        preset_multipliers = {
            "ultrafast": 0.5,
            "superfast": 0.6,
            "veryfast": 0.8,
            "faster": 1.0,
            "fast": 1.2,
            "medium": 1.5,
            "slow": 3.0,
            "slower": 5.0,
            "veryslow": 10.0,
        }
        multiplier = preset_multipliers.get(preset.video.preset, 1.5)

    return timeline_duration * multiplier
