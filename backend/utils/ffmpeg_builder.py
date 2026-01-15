"""
FFmpeg command builder for timeline rendering.

This module converts OTIO-inspired timeline structures into FFmpeg filter_complex
commands for video rendering. It supports:
- Multi-track video/audio composition
- Clips with in/out points (trim)
- Transitions (dissolve, fade, wipe)
- Effects (speed changes, freeze frames)
- Nested compositions (stacks within tracks)
- Generator references (solid colors, test patterns)

The builder generates FFmpeg commands that can be executed by the render job.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from models.timeline_models import (
    Clip,
    ExternalReference,
    FreezeFrame,
    Gap,
    GeneratorReference,
    LinearTimeWarp,
    MissingReference,
    RationalTime,
    Stack,
    Timeline,
    Track,
    TrackKind,
    Transition,
    TransitionType,
)
from models.render_models import RenderPreset, VideoCodec

logger = logging.getLogger(__name__)


# =============================================================================
# DATA STRUCTURES
# =============================================================================


@dataclass
class InputFile:
    """Represents an input file for FFmpeg."""

    index: int  # FFmpeg input index (0, 1, 2, ...)
    asset_id: str
    file_path: str
    duration: float | None = None  # Duration in seconds


@dataclass
class FilterNode:
    """A node in the FFmpeg filter graph."""

    name: str  # Output label (e.g., "v0", "a0", "vout")
    filter_expr: str  # The filter expression


@dataclass
class TrackSegment:
    """A segment of a track with timing information."""

    start_time: float  # Start time on timeline (seconds)
    duration: float  # Duration on timeline (seconds)
    source_start: float  # Start time in source (seconds)
    source_duration: float  # Duration in source (may differ due to speed effects)
    input_index: int | None  # FFmpeg input index (None for gaps/generators)
    is_gap: bool = False
    is_generator: bool = False
    generator_params: dict[str, Any] = field(default_factory=dict)
    speed_factor: float = 1.0  # 1.0 = normal, 0.5 = half speed, 2.0 = double
    is_freeze: bool = False
    effects: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class TransitionInfo:
    """Information about a transition between segments."""

    position: int  # Index in track where transition occurs
    transition_type: TransitionType
    duration: float  # Transition duration in seconds
    in_offset: float  # Seconds into outgoing clip
    out_offset: float  # Seconds from incoming clip


@dataclass 
class FFmpegCommand:
    """Complete FFmpeg command structure."""

    inputs: list[str]  # -i arguments
    filter_complex: str  # -filter_complex argument
    output_maps: list[str]  # -map arguments
    output_options: list[str]  # Encoding options
    output_file: str


# =============================================================================
# TIMELINE TO FFMPEG CONVERTER
# =============================================================================


class TimelineToFFmpeg:
    """
    Converts an OTIO-inspired Timeline to FFmpeg filter_complex commands.

    Usage:
        converter = TimelineToFFmpeg(timeline, asset_map, preset)
        command = converter.build()
        # command.inputs, command.filter_complex, etc.
    """

    def __init__(
        self,
        timeline: Timeline,
        asset_map: dict[str, str],  # asset_id -> file path
        preset: RenderPreset,
        output_path: str,
    ):
        self.timeline = timeline
        self.asset_map = asset_map
        self.preset = preset
        self.output_path = output_path

        # State for building
        self._inputs: list[InputFile] = []
        self._input_index_map: dict[str, int] = {}  # asset_id -> input index
        self._filter_counter = 0
        self._video_filters: list[str] = []
        self._audio_filters: list[str] = []

    def build(self) -> FFmpegCommand:
        """Build the complete FFmpeg command."""
        # Reset state
        self._inputs = []
        self._input_index_map = {}
        self._filter_counter = 0
        self._video_filters = []
        self._audio_filters = []

        # Collect all inputs from timeline
        self._collect_inputs()

        # Build filter graph for each track type
        video_out = self._build_video_graph()
        audio_out = self._build_audio_graph()

        # Combine filter graphs
        filter_complex = self._combine_filters()

        # Build output options
        output_options = self._build_output_options()

        # Build maps
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
        """Build complete FFmpeg command as a string."""
        cmd = self.build()

        parts = ["ffmpeg", "-y"]  # -y to overwrite output

        # Add inputs
        for inp in cmd.inputs:
            parts.append(inp)

        # Add filter_complex
        if cmd.filter_complex:
            # Escape for shell
            filter_escaped = cmd.filter_complex.replace("'", "'\\''")
            parts.append(f"-filter_complex '{filter_escaped}'")

        # Add maps
        for m in cmd.output_maps:
            parts.append(f"-map {m}")

        # Add output options
        parts.extend(cmd.output_options)

        # Add output file
        parts.append(f'"{cmd.output_file}"')

        return " ".join(parts)

    def _collect_inputs(self) -> None:
        """Collect all input files from timeline clips."""
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
        """Build filter graph for video tracks."""
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

        # If multiple video tracks, overlay them
        if len(track_outputs) == 1:
            return track_outputs[0]
        else:
            return self._overlay_video_tracks(track_outputs)

    def _build_audio_graph(self) -> str | None:
        """Build filter graph for audio tracks."""
        audio_tracks = self.timeline.audio_tracks
        if not audio_tracks:
            # Check if video tracks have audio
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

        # Mix multiple audio tracks
        if len(track_outputs) == 1:
            return track_outputs[0]
        else:
            return self._mix_audio_tracks(track_outputs)

    def _process_video_track(self, track: Track, track_idx: int) -> str | None:
        """Process a single video track into filter expressions."""
        segments = self._extract_track_segments(track)
        transitions = self._extract_transitions(track)

        if not segments:
            return None

        # Process each segment
        segment_outputs: list[str] = []

        for seg_idx, segment in enumerate(segments):
            seg_out = self._process_video_segment(segment, track_idx, seg_idx)
            if seg_out:
                segment_outputs.append(seg_out)

        if not segment_outputs:
            return None

        # Apply transitions between segments
        if transitions and len(segment_outputs) > 1:
            return self._apply_video_transitions(segment_outputs, transitions)
        elif len(segment_outputs) == 1:
            return segment_outputs[0]
        else:
            return self._concat_video_segments(segment_outputs)

    def _process_audio_track(self, track: Track, track_idx: int) -> str | None:
        """Process a single audio track into filter expressions."""
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

        # Apply transitions between segments
        if transitions and len(segment_outputs) > 1:
            return self._apply_audio_transitions(segment_outputs, transitions)
        elif len(segment_outputs) == 1:
            return segment_outputs[0]
        else:
            return self._concat_audio_segments(segment_outputs)

    def _extract_track_segments(self, track: Track) -> list[TrackSegment]:
        """Extract segments from a track with timing information."""
        segments: list[TrackSegment] = []
        current_time = 0.0

        for child in track.children:
            if isinstance(child, Transition):
                # Transitions are handled separately
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
                # Nested stack - recursively process
                # For now, treat as a single segment
                stack_duration = child.duration().to_seconds()
                segments.append(
                    TrackSegment(
                        start_time=current_time,
                        duration=stack_duration,
                        source_start=0,
                        source_duration=stack_duration,
                        input_index=None,
                        is_gap=True,  # Placeholder
                    )
                )
                current_time += stack_duration

        return segments

    def _clip_to_segment(self, clip: Clip, timeline_start: float) -> TrackSegment:
        """Convert a Clip to a TrackSegment."""
        source_start = clip.source_range.start_time.to_seconds()
        source_duration = clip.source_range.duration.to_seconds()

        # Default values
        input_index: int | None = None
        is_generator = False
        generator_params: dict[str, Any] = {}
        speed_factor = 1.0
        is_freeze = False

        # Get input index from media reference
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
            # Treat missing as gap
            return TrackSegment(
                start_time=timeline_start,
                duration=source_duration,
                source_start=0,
                source_duration=source_duration,
                input_index=None,
                is_gap=True,
            )

        # Process effects
        effects_data: list[dict[str, Any]] = []
        for effect in clip.effects:
            if isinstance(effect, LinearTimeWarp):
                speed_factor = effect.time_scalar
                effects_data.append({"type": "speed", "factor": speed_factor})
            elif isinstance(effect, FreezeFrame):
                is_freeze = True
                effects_data.append({"type": "freeze"})
            else:
                # Generic effect
                effects_data.append({
                    "type": "generic",
                    "name": effect.effect_name,
                    "metadata": effect.metadata,
                })

        # Calculate timeline duration (affected by speed)
        timeline_duration = source_duration / speed_factor if speed_factor != 0 else source_duration

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
        """Extract transition information from track."""
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
        """Generate filter expression for a video segment."""
        label = f"v{track_idx}_{seg_idx}"

        if segment.is_gap:
            # Generate black frames for gap
            return self._generate_gap_video(segment, label)

        if segment.is_generator:
            return self._generate_generator_video(segment, label)

        if segment.input_index is None:
            return None

        filters: list[str] = []
        input_label = f"{segment.input_index}:v"

        # Trim filter
        trim_filter = (
            f"trim=start={segment.source_start}:duration={segment.source_duration}"
        )
        filters.append(trim_filter)

        # Reset timestamps
        filters.append("setpts=PTS-STARTPTS")

        # Speed effect
        if segment.is_freeze:
            # Freeze frame: select single frame and loop
            filters.append(f"select='eq(n,0)',loop=loop=-1:size=1")
        elif segment.speed_factor != 1.0:
            # Speed change using setpts
            pts_factor = 1.0 / segment.speed_factor
            filters.append(f"setpts={pts_factor}*PTS")

        # Scale to output resolution if specified
        if self.preset.video.width and self.preset.video.height:
            filters.append(
                f"scale={self.preset.video.width}:{self.preset.video.height}:force_original_aspect_ratio=decrease,"
                f"pad={self.preset.video.width}:{self.preset.video.height}:(ow-iw)/2:(oh-ih)/2"
            )

        # Build filter chain
        filter_chain = ",".join(filters)
        self._video_filters.append(f"[{input_label}]{filter_chain}[{label}]")

        return label

    def _process_audio_segment(
        self, segment: TrackSegment, track_idx: int, seg_idx: int
    ) -> str | None:
        """Generate filter expression for an audio segment."""
        label = f"a{track_idx}_{seg_idx}"

        if segment.is_gap or segment.is_generator:
            # Generate silence for gap
            return self._generate_gap_audio(segment, label)

        if segment.input_index is None:
            return None

        filters: list[str] = []
        input_label = f"{segment.input_index}:a"

        # Trim filter
        trim_filter = (
            f"atrim=start={segment.source_start}:duration={segment.source_duration}"
        )
        filters.append(trim_filter)

        # Reset timestamps
        filters.append("asetpts=PTS-STARTPTS")

        # Speed effect
        if segment.is_freeze:
            # Audio freeze - just repeat
            pass  # Not typical for audio
        elif segment.speed_factor != 1.0:
            # Audio tempo adjustment
            # atempo only supports 0.5 to 2.0, so chain for extreme values
            tempo = segment.speed_factor
            tempo_filters = self._build_atempo_chain(tempo)
            filters.extend(tempo_filters)

        # Build filter chain
        filter_chain = ",".join(filters)
        self._audio_filters.append(f"[{input_label}]{filter_chain}[{label}]")

        return label

    def _build_atempo_chain(self, tempo: float) -> list[str]:
        """Build atempo filter chain for speed changes outside 0.5-2.0 range."""
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
        """Generate black video for a gap."""
        width = self.preset.video.width or 1920
        height = self.preset.video.height or 1080
        framerate = self.preset.video.framerate or 24

        # Use color source for gap
        self._video_filters.append(
            f"color=c=black:s={width}x{height}:d={segment.duration}:r={framerate}[{label}]"
        )
        return label

    def _generate_gap_audio(self, segment: TrackSegment, label: str) -> str:
        """Generate silence for an audio gap."""
        sample_rate = self.preset.audio.sample_rate
        channels = self.preset.audio.channels

        self._audio_filters.append(
            f"anullsrc=r={sample_rate}:cl={'stereo' if channels == 2 else 'mono'},"
            f"atrim=duration={segment.duration}[{label}]"
        )
        return label

    def _generate_generator_video(self, segment: TrackSegment, label: str) -> str:
        """Generate video from a generator reference."""
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
            # SMPTE color bars
            self._video_filters.append(
                f"smptebars=s={width}x{height}:d={segment.duration}:r={framerate}[{label}]"
            )
        else:
            # Default to black
            self._video_filters.append(
                f"color=c=black:s={width}x{height}:d={segment.duration}:r={framerate}[{label}]"
            )

        return label

    def _apply_video_transitions(
        self, segments: list[str], transitions: list[TransitionInfo]
    ) -> str:
        """Apply video transitions between segments."""
        if not transitions:
            return self._concat_video_segments(segments)

        result = segments[0]
        transition_idx = 0

        for i in range(1, len(segments)):
            out_label = f"vtrans_{self._filter_counter}"
            self._filter_counter += 1

            # Check if there's a transition at this position
            trans = None
            if transition_idx < len(transitions):
                if transitions[transition_idx].position == i:
                    trans = transitions[transition_idx]
                    transition_idx += 1

            if trans:
                # Apply transition
                trans_type = self._map_transition_type(trans.transition_type)
                offset = max(0, trans.duration / 2)  # Approximate offset

                self._video_filters.append(
                    f"[{result}][{segments[i]}]xfade=transition={trans_type}:"
                    f"duration={trans.duration}:offset={offset}[{out_label}]"
                )
            else:
                # Simple concat
                self._video_filters.append(
                    f"[{result}][{segments[i]}]concat=n=2:v=1:a=0[{out_label}]"
                )

            result = out_label

        return result

    def _apply_audio_transitions(
        self, segments: list[str], transitions: list[TransitionInfo]
    ) -> str:
        """Apply audio transitions (crossfades) between segments."""
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
                # Apply crossfade
                self._audio_filters.append(
                    f"[{result}][{segments[i]}]acrossfade=d={trans.duration}[{out_label}]"
                )
            else:
                # Simple concat
                self._audio_filters.append(
                    f"[{result}][{segments[i]}]concat=n=2:v=0:a=1[{out_label}]"
                )

            result = out_label

        return result

    def _concat_video_segments(self, segments: list[str]) -> str:
        """Concatenate video segments without transitions."""
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
        """Concatenate audio segments without transitions."""
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
        """Overlay multiple video tracks (higher index on top)."""
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
        """Mix multiple audio tracks together."""
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
        """Extract audio from video tracks when no dedicated audio tracks exist."""
        video_tracks = self.timeline.video_tracks
        if not video_tracks:
            return None

        # Process first video track's audio
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
        """Map OTIO transition type to FFmpeg xfade transition."""
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
        """Combine all filter expressions into filter_complex string."""
        all_filters = self._video_filters + self._audio_filters
        return ";".join(all_filters)

    def _build_output_options(self) -> list[str]:
        """Build FFmpeg output encoding options."""
        options: list[str] = []

        # Video codec
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

        # Video quality
        if self.preset.video.crf is not None:
            if self.preset.use_gpu:
                # NVENC uses -cq instead of -crf
                options.extend(["-cq", str(self.preset.video.crf)])
            else:
                options.extend(["-crf", str(self.preset.video.crf)])

        if self.preset.video.bitrate:
            options.extend(["-b:v", self.preset.video.bitrate])

        # Encoding preset
        if self.preset.use_gpu:
            # NVENC presets are different
            nvenc_preset = self._map_nvenc_preset(self.preset.video.preset)
            options.extend(["-preset", nvenc_preset])
        else:
            options.extend(["-preset", self.preset.video.preset])

        # Pixel format
        options.extend(["-pix_fmt", self.preset.video.pixel_format])

        # Audio codec
        if self.preset.audio.codec.value == "aac":
            options.extend(["-c:a", "aac"])
        elif self.preset.audio.codec.value == "mp3":
            options.extend(["-c:a", "libmp3lame"])

        options.extend(["-b:a", self.preset.audio.bitrate])
        options.extend(["-ar", str(self.preset.audio.sample_rate)])
        options.extend(["-ac", str(self.preset.audio.channels)])

        # Container options
        options.extend(["-movflags", "+faststart"])  # Enable streaming

        return options

    def _map_nvenc_preset(self, preset: str) -> str:
        """Map libx264 presets to NVENC presets."""
        # NVENC presets: slow, medium, fast, hp, hq, bd, ll, llhq, llhp, lossless
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


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================


def build_render_command(
    timeline_dict: dict[str, Any],
    asset_map: dict[str, str],
    preset: RenderPreset,
    output_path: str,
) -> str:
    """
    Convenience function to build FFmpeg command from timeline dict.

    Args:
        timeline_dict: Timeline serialized as dict (from checkpoint snapshot)
        asset_map: Mapping of asset_id -> file path
        preset: Render preset configuration
        output_path: Output file path

    Returns:
        FFmpeg command string ready for execution
    """
    timeline = Timeline.model_validate(timeline_dict)
    converter = TimelineToFFmpeg(timeline, asset_map, preset, output_path)
    return converter.build_command_string()


def estimate_render_duration(timeline: Timeline, preset: RenderPreset) -> float:
    """
    Estimate how long rendering will take.

    This is a rough estimate based on timeline duration and preset complexity.

    Returns:
        Estimated render time in seconds
    """
    timeline_duration = timeline.duration.to_seconds()

    # Base multiplier (realtime = 1.0)
    if preset.use_gpu:
        # GPU is typically 5-10x faster
        multiplier = 0.1 if preset.quality.value in ["draft", "standard"] else 0.2
    else:
        # CPU encoding speed depends on preset
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
