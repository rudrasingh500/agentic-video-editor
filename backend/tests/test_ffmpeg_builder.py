"""
Tests for the FFmpeg command builder.

These tests verify that timeline structures are correctly converted
to FFmpeg filter_complex commands.
"""

import pytest
from uuid import uuid4

from models.timeline_models import (
    Clip,
    ExternalReference,
    Gap,
    GeneratorReference,
    LinearTimeWarp,
    RationalTime,
    Stack,
    Timeline,
    TimeRange,
    Track,
    TrackKind,
    Transition,
    TransitionType,
)
from models.render_models import RenderPreset
from utils.ffmpeg_builder import (
    TimelineToFFmpeg,
    build_render_command,
    estimate_render_duration,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def sample_asset_map() -> dict[str, str]:
    """Sample asset mapping for tests."""
    return {
        "asset-1": "/inputs/project/videos/clip1.mp4",
        "asset-2": "/inputs/project/videos/clip2.mp4",
        "asset-3": "/inputs/project/audio/music.mp3",
    }


@pytest.fixture
def draft_preset() -> RenderPreset:
    """Draft quality preset for tests."""
    return RenderPreset.draft_preview()


@pytest.fixture
def standard_preset() -> RenderPreset:
    """Standard quality preset for tests."""
    return RenderPreset.standard_export()


@pytest.fixture
def simple_timeline() -> Timeline:
    """Simple timeline with one video clip."""
    clip = Clip(
        name="Test Clip",
        media_reference=ExternalReference(
            asset_id=uuid4(),
            target_url="gs://bucket/clip1.mp4",
        ),
        source_range=TimeRange(
            start_time=RationalTime(value=0, rate=24),
            duration=RationalTime(value=120, rate=24),  # 5 seconds
        ),
    )

    video_track = Track(
        name="Video 1",
        kind=TrackKind.VIDEO,
        children=[clip],
    )

    return Timeline(
        name="Test Timeline",
        tracks=Stack(
            name="Timeline Stack",
            children=[video_track],
        ),
    )


@pytest.fixture
def multi_clip_timeline() -> Timeline:
    """Timeline with multiple clips."""
    clip1 = Clip(
        name="Clip 1",
        media_reference=ExternalReference(
            asset_id=uuid4(),
            target_url="gs://bucket/clip1.mp4",
        ),
        source_range=TimeRange(
            start_time=RationalTime(value=0, rate=24),
            duration=RationalTime(value=48, rate=24),  # 2 seconds
        ),
    )

    clip2 = Clip(
        name="Clip 2",
        media_reference=ExternalReference(
            asset_id=uuid4(),
            target_url="gs://bucket/clip2.mp4",
        ),
        source_range=TimeRange(
            start_time=RationalTime(value=24, rate=24),  # Start at 1 second
            duration=RationalTime(value=72, rate=24),  # 3 seconds
        ),
    )

    video_track = Track(
        name="Video 1",
        kind=TrackKind.VIDEO,
        children=[clip1, clip2],
    )

    return Timeline(
        name="Multi Clip Timeline",
        tracks=Stack(
            name="Timeline Stack",
            children=[video_track],
        ),
    )


@pytest.fixture
def timeline_with_gap() -> Timeline:
    """Timeline with a gap between clips."""
    clip1 = Clip(
        name="Clip 1",
        media_reference=ExternalReference(
            asset_id=uuid4(),
            target_url="gs://bucket/clip1.mp4",
        ),
        source_range=TimeRange(
            start_time=RationalTime(value=0, rate=24),
            duration=RationalTime(value=48, rate=24),
        ),
    )

    gap = Gap(
        source_range=TimeRange(
            start_time=RationalTime(value=0, rate=24),
            duration=RationalTime(value=24, rate=24),  # 1 second gap
        ),
    )

    clip2 = Clip(
        name="Clip 2",
        media_reference=ExternalReference(
            asset_id=uuid4(),
            target_url="gs://bucket/clip2.mp4",
        ),
        source_range=TimeRange(
            start_time=RationalTime(value=0, rate=24),
            duration=RationalTime(value=48, rate=24),
        ),
    )

    video_track = Track(
        name="Video 1",
        kind=TrackKind.VIDEO,
        children=[clip1, gap, clip2],
    )

    return Timeline(
        name="Gap Timeline",
        tracks=Stack(
            name="Timeline Stack",
            children=[video_track],
        ),
    )


@pytest.fixture
def timeline_with_transition() -> Timeline:
    """Timeline with a transition between clips."""
    clip1 = Clip(
        name="Clip 1",
        media_reference=ExternalReference(
            asset_id=uuid4(),
            target_url="gs://bucket/clip1.mp4",
        ),
        source_range=TimeRange(
            start_time=RationalTime(value=0, rate=24),
            duration=RationalTime(value=72, rate=24),  # 3 seconds
        ),
    )

    transition = Transition(
        name="Dissolve",
        transition_type=TransitionType.SMPTE_DISSOLVE,
        in_offset=RationalTime(value=12, rate=24),  # 0.5 seconds
        out_offset=RationalTime(value=12, rate=24),
    )

    clip2 = Clip(
        name="Clip 2",
        media_reference=ExternalReference(
            asset_id=uuid4(),
            target_url="gs://bucket/clip2.mp4",
        ),
        source_range=TimeRange(
            start_time=RationalTime(value=0, rate=24),
            duration=RationalTime(value=72, rate=24),  # 3 seconds
        ),
    )

    video_track = Track(
        name="Video 1",
        kind=TrackKind.VIDEO,
        children=[clip1, transition, clip2],
    )

    return Timeline(
        name="Transition Timeline",
        tracks=Stack(
            name="Timeline Stack",
            children=[video_track],
        ),
    )


@pytest.fixture
def timeline_with_speed_effect() -> Timeline:
    """Timeline with a speed-adjusted clip."""
    clip = Clip(
        name="Slow Motion Clip",
        media_reference=ExternalReference(
            asset_id=uuid4(),
            target_url="gs://bucket/clip1.mp4",
        ),
        source_range=TimeRange(
            start_time=RationalTime(value=0, rate=24),
            duration=RationalTime(value=48, rate=24),
        ),
        effects=[
            LinearTimeWarp(
                effect_name="Speed",
                time_scalar=0.5,  # Half speed (slow motion)
            ),
        ],
    )

    video_track = Track(
        name="Video 1",
        kind=TrackKind.VIDEO,
        children=[clip],
    )

    return Timeline(
        name="Speed Timeline",
        tracks=Stack(
            name="Timeline Stack",
            children=[video_track],
        ),
    )


@pytest.fixture
def timeline_with_generator() -> Timeline:
    """Timeline with a solid color generator."""
    generator_clip = Clip(
        name="Black Screen",
        media_reference=GeneratorReference(
            generator_kind="SolidColor",
            parameters={"color": "black"},
        ),
        source_range=TimeRange(
            start_time=RationalTime(value=0, rate=24),
            duration=RationalTime(value=48, rate=24),  # 2 seconds
        ),
    )

    video_track = Track(
        name="Video 1",
        kind=TrackKind.VIDEO,
        children=[generator_clip],
    )

    return Timeline(
        name="Generator Timeline",
        tracks=Stack(
            name="Timeline Stack",
            children=[video_track],
        ),
    )


# =============================================================================
# TIMELINE PARSING TESTS
# =============================================================================


class TestTimelineToFFmpeg:
    """Tests for the TimelineToFFmpeg converter."""

    def test_collect_inputs_single_clip(self, simple_timeline, draft_preset):
        """Test that inputs are collected from a single clip."""
        # Get the asset ID from the clip
        clip = simple_timeline.find_clips()[0]
        asset_id = str(clip.media_reference.asset_id)

        asset_map = {asset_id: "/inputs/clip1.mp4"}

        converter = TimelineToFFmpeg(
            simple_timeline, asset_map, draft_preset, "/outputs/render.mp4"
        )
        converter._collect_inputs()

        assert len(converter._inputs) == 1
        assert converter._inputs[0].file_path == "/inputs/clip1.mp4"
        assert asset_id in converter._input_index_map

    def test_collect_inputs_multiple_clips(self, multi_clip_timeline, draft_preset):
        """Test that inputs are collected from multiple clips."""
        clips = multi_clip_timeline.find_clips()
        asset_map = {}

        for i, clip in enumerate(clips):
            asset_id = str(clip.media_reference.asset_id)
            asset_map[asset_id] = f"/inputs/clip{i + 1}.mp4"

        converter = TimelineToFFmpeg(
            multi_clip_timeline, asset_map, draft_preset, "/outputs/render.mp4"
        )
        converter._collect_inputs()

        assert len(converter._inputs) == 2

    def test_missing_asset_warning(self, simple_timeline, draft_preset, caplog):
        """Test that missing assets generate warnings."""
        # Empty asset map
        asset_map = {}

        converter = TimelineToFFmpeg(
            simple_timeline, asset_map, draft_preset, "/outputs/render.mp4"
        )
        converter._collect_inputs()

        assert len(converter._inputs) == 0
        assert "not found in asset_map" in caplog.text


class TestSegmentExtraction:
    """Tests for track segment extraction."""

    def test_extract_clip_segment(self, simple_timeline, draft_preset):
        """Test extracting a segment from a clip."""
        clip = simple_timeline.find_clips()[0]
        asset_id = str(clip.media_reference.asset_id)
        asset_map = {asset_id: "/inputs/clip1.mp4"}

        converter = TimelineToFFmpeg(
            simple_timeline, asset_map, draft_preset, "/outputs/render.mp4"
        )
        converter._collect_inputs()

        video_track = simple_timeline.video_tracks[0]
        segments = converter._extract_track_segments(video_track)

        assert len(segments) == 1
        assert segments[0].start_time == 0.0
        assert segments[0].duration == 5.0  # 120 frames at 24fps
        assert segments[0].is_gap is False

    def test_extract_gap_segment(self, timeline_with_gap, draft_preset):
        """Test extracting a gap segment."""
        clips = timeline_with_gap.find_clips()
        asset_map = {}

        for clip in clips:
            asset_id = str(clip.media_reference.asset_id)
            asset_map[asset_id] = f"/inputs/{clip.name}.mp4"

        converter = TimelineToFFmpeg(
            timeline_with_gap, asset_map, draft_preset, "/outputs/render.mp4"
        )
        converter._collect_inputs()

        video_track = timeline_with_gap.video_tracks[0]
        segments = converter._extract_track_segments(video_track)

        assert len(segments) == 3
        assert segments[0].is_gap is False
        assert segments[1].is_gap is True
        assert segments[1].duration == 1.0  # 1 second gap
        assert segments[2].is_gap is False

    def test_extract_speed_effect(self, timeline_with_speed_effect, draft_preset):
        """Test extracting speed effect information."""
        clip = timeline_with_speed_effect.find_clips()[0]
        asset_id = str(clip.media_reference.asset_id)
        asset_map = {asset_id: "/inputs/clip1.mp4"}

        converter = TimelineToFFmpeg(
            timeline_with_speed_effect, asset_map, draft_preset, "/outputs/render.mp4"
        )
        converter._collect_inputs()

        video_track = timeline_with_speed_effect.video_tracks[0]
        segments = converter._extract_track_segments(video_track)

        assert len(segments) == 1
        assert segments[0].speed_factor == 0.5
        # Duration should be doubled due to half speed
        assert (
            segments[0].duration == 4.0
        )  # 2 seconds source at 0.5x = 4 seconds output


class TestFilterGeneration:
    """Tests for FFmpeg filter generation."""

    def test_generate_trim_filter(self, simple_timeline, draft_preset):
        """Test that trim filters are generated correctly."""
        clip = simple_timeline.find_clips()[0]
        asset_id = str(clip.media_reference.asset_id)
        asset_map = {asset_id: "/inputs/clip1.mp4"}

        converter = TimelineToFFmpeg(
            simple_timeline, asset_map, draft_preset, "/outputs/render.mp4"
        )
        cmd = converter.build()

        # Check filter contains trim
        assert "trim=" in cmd.filter_complex
        assert "setpts=PTS-STARTPTS" in cmd.filter_complex

    def test_generate_gap_video(self, timeline_with_gap, draft_preset):
        """Test that black video is generated for gaps."""
        clips = timeline_with_gap.find_clips()
        asset_map = {}

        for clip in clips:
            asset_id = str(clip.media_reference.asset_id)
            asset_map[asset_id] = f"/inputs/{clip.name}.mp4"

        converter = TimelineToFFmpeg(
            timeline_with_gap, asset_map, draft_preset, "/outputs/render.mp4"
        )
        cmd = converter.build()

        # Check for color source (black frames for gap)
        assert "color=c=black" in cmd.filter_complex

    def test_generate_concat_filter(self, multi_clip_timeline, draft_preset):
        """Test that concat filter is generated for multiple clips."""
        clips = multi_clip_timeline.find_clips()
        asset_map = {}

        for i, clip in enumerate(clips):
            asset_id = str(clip.media_reference.asset_id)
            asset_map[asset_id] = f"/inputs/clip{i + 1}.mp4"

        converter = TimelineToFFmpeg(
            multi_clip_timeline, asset_map, draft_preset, "/outputs/render.mp4"
        )
        cmd = converter.build()

        # Check for concat filter
        assert "concat=" in cmd.filter_complex

    def test_generate_transition_filter(self, timeline_with_transition, draft_preset):
        """Test that xfade filter is generated for transitions."""
        clips = timeline_with_transition.find_clips()
        asset_map = {}

        for i, clip in enumerate(clips):
            asset_id = str(clip.media_reference.asset_id)
            asset_map[asset_id] = f"/inputs/clip{i + 1}.mp4"

        converter = TimelineToFFmpeg(
            timeline_with_transition, asset_map, draft_preset, "/outputs/render.mp4"
        )
        cmd = converter.build()

        # Check for xfade filter (dissolve transition)
        assert "xfade=" in cmd.filter_complex
        assert "dissolve" in cmd.filter_complex

    def test_generate_speed_filter(self, timeline_with_speed_effect, draft_preset):
        """Test that setpts filter is generated for speed changes."""
        clip = timeline_with_speed_effect.find_clips()[0]
        asset_id = str(clip.media_reference.asset_id)
        asset_map = {asset_id: "/inputs/clip1.mp4"}

        converter = TimelineToFFmpeg(
            timeline_with_speed_effect, asset_map, draft_preset, "/outputs/render.mp4"
        )
        cmd = converter.build()

        # Check for setpts with speed factor (0.5 speed = 2.0 PTS multiplier)
        assert "setpts=" in cmd.filter_complex
        # Should have 2.0*PTS for half speed
        assert "2.0*PTS" in cmd.filter_complex or "2*PTS" in cmd.filter_complex

    def test_generate_solid_color(self, timeline_with_generator, draft_preset):
        """Test that solid color generator creates color filter."""
        converter = TimelineToFFmpeg(
            timeline_with_generator, {}, draft_preset, "/outputs/render.mp4"
        )
        cmd = converter.build()

        # Check for color source
        assert "color=c=black" in cmd.filter_complex


class TestOutputOptions:
    """Tests for output encoding options."""

    def test_cpu_encoding_options(self, simple_timeline):
        """Test CPU encoding options (libx264)."""
        clip = simple_timeline.find_clips()[0]
        asset_id = str(clip.media_reference.asset_id)
        asset_map = {asset_id: "/inputs/clip1.mp4"}

        preset = RenderPreset.standard_export()  # use_gpu=False

        converter = TimelineToFFmpeg(
            simple_timeline, asset_map, preset, "/outputs/render.mp4"
        )
        cmd = converter.build()

        assert "-c:v" in cmd.output_options
        assert "libx264" in cmd.output_options
        assert "-crf" in cmd.output_options

    def test_gpu_encoding_options(self, simple_timeline):
        """Test GPU encoding options (h264_nvenc)."""
        clip = simple_timeline.find_clips()[0]
        asset_id = str(clip.media_reference.asset_id)
        asset_map = {asset_id: "/inputs/clip1.mp4"}

        preset = RenderPreset.high_quality_export()  # use_gpu=True

        converter = TimelineToFFmpeg(
            simple_timeline, asset_map, preset, "/outputs/render.mp4"
        )
        cmd = converter.build()

        assert "-c:v" in cmd.output_options
        assert "h264_nvenc" in cmd.output_options
        assert "-cq" in cmd.output_options  # GPU uses -cq instead of -crf

    def test_audio_encoding_options(self, simple_timeline, draft_preset):
        """Test audio encoding options."""
        clip = simple_timeline.find_clips()[0]
        asset_id = str(clip.media_reference.asset_id)
        asset_map = {asset_id: "/inputs/clip1.mp4"}

        converter = TimelineToFFmpeg(
            simple_timeline, asset_map, draft_preset, "/outputs/render.mp4"
        )
        cmd = converter.build()

        assert "-c:a" in cmd.output_options
        assert "aac" in cmd.output_options
        assert "-b:a" in cmd.output_options

    def test_faststart_option(self, simple_timeline, draft_preset):
        """Test that faststart is enabled for streaming."""
        clip = simple_timeline.find_clips()[0]
        asset_id = str(clip.media_reference.asset_id)
        asset_map = {asset_id: "/inputs/clip1.mp4"}

        converter = TimelineToFFmpeg(
            simple_timeline, asset_map, draft_preset, "/outputs/render.mp4"
        )
        cmd = converter.build()

        assert "-movflags" in cmd.output_options
        assert "+faststart" in cmd.output_options


class TestCommandBuilding:
    """Tests for building complete FFmpeg commands."""

    def test_build_command_string(self, simple_timeline, draft_preset):
        """Test building a complete command string."""
        clip = simple_timeline.find_clips()[0]
        asset_id = str(clip.media_reference.asset_id)
        asset_map = {asset_id: "/inputs/clip1.mp4"}

        converter = TimelineToFFmpeg(
            simple_timeline, asset_map, draft_preset, "/outputs/render.mp4"
        )
        cmd_str = converter.build_command_string()

        assert cmd_str.startswith("ffmpeg -y")
        assert "-i /inputs/clip1.mp4" in cmd_str
        assert "-filter_complex" in cmd_str
        assert '"/outputs/render.mp4"' in cmd_str

    def test_build_render_command_helper(self, simple_timeline, draft_preset):
        """Test the convenience helper function."""
        clip = simple_timeline.find_clips()[0]
        asset_id = str(clip.media_reference.asset_id)
        asset_map = {asset_id: "/inputs/clip1.mp4"}

        timeline_dict = simple_timeline.model_dump()

        cmd_str = build_render_command(
            timeline_dict, asset_map, draft_preset, "/outputs/render.mp4"
        )

        assert cmd_str.startswith("ffmpeg -y")


class TestDurationEstimation:
    """Tests for render duration estimation."""

    def test_estimate_cpu_duration(self, simple_timeline):
        """Test duration estimation for CPU rendering."""
        preset = RenderPreset.standard_export()

        estimated = estimate_render_duration(simple_timeline, preset)

        # 5 second timeline with medium preset (~1.5x realtime)
        assert estimated >= 5.0  # At least as long as timeline
        assert estimated <= 30.0  # Not unreasonably long

    def test_estimate_gpu_duration(self, simple_timeline):
        """Test duration estimation for GPU rendering."""
        preset = RenderPreset.high_quality_export()

        estimated = estimate_render_duration(simple_timeline, preset)

        # GPU should be faster
        assert estimated >= 0.5  # At least some time
        assert estimated <= 5.0  # Faster than realtime


# =============================================================================
# RENDER MODELS TESTS
# =============================================================================


class TestRenderPresets:
    """Tests for render preset configurations."""

    def test_draft_preview_preset(self):
        """Test draft preview preset settings."""
        preset = RenderPreset.draft_preview()

        assert preset.quality.value == "draft"
        assert preset.video.width == 1280
        assert preset.video.height == 720
        assert preset.video.crf == 28
        assert preset.video.preset == "veryfast"
        assert preset.use_gpu is False

    def test_standard_export_preset(self):
        """Test standard export preset settings."""
        preset = RenderPreset.standard_export()

        assert preset.quality.value == "standard"
        assert preset.video.crf == 23
        assert preset.video.preset == "medium"
        assert preset.use_gpu is False

    def test_high_quality_preset(self):
        """Test high quality preset settings."""
        preset = RenderPreset.high_quality_export()

        assert preset.quality.value == "high"
        assert preset.video.crf == 18
        assert preset.video.preset == "slow"
        assert preset.use_gpu is True

    def test_maximum_quality_preset(self):
        """Test maximum quality preset settings."""
        preset = RenderPreset.maximum_quality_export()

        assert preset.quality.value == "maximum"
        assert preset.video.crf == 15
        assert preset.video.preset == "veryslow"
        assert preset.use_gpu is True


class TestAtempoChain:
    """Tests for audio tempo filter chain building."""

    def test_normal_speed(self, simple_timeline, draft_preset):
        """Test no atempo filter for normal speed."""
        clip = simple_timeline.find_clips()[0]
        asset_id = str(clip.media_reference.asset_id)
        asset_map = {asset_id: "/inputs/clip1.mp4"}

        converter = TimelineToFFmpeg(
            simple_timeline, asset_map, draft_preset, "/outputs/render.mp4"
        )

        chain = converter._build_atempo_chain(1.0)
        assert chain == []

    def test_half_speed(self, simple_timeline, draft_preset):
        """Test atempo filter for half speed."""
        clip = simple_timeline.find_clips()[0]
        asset_id = str(clip.media_reference.asset_id)
        asset_map = {asset_id: "/inputs/clip1.mp4"}

        converter = TimelineToFFmpeg(
            simple_timeline, asset_map, draft_preset, "/outputs/render.mp4"
        )

        chain = converter._build_atempo_chain(0.5)
        assert "atempo=0.5" in chain

    def test_double_speed(self, simple_timeline, draft_preset):
        """Test atempo filter for double speed."""
        clip = simple_timeline.find_clips()[0]
        asset_id = str(clip.media_reference.asset_id)
        asset_map = {asset_id: "/inputs/clip1.mp4"}

        converter = TimelineToFFmpeg(
            simple_timeline, asset_map, draft_preset, "/outputs/render.mp4"
        )

        chain = converter._build_atempo_chain(2.0)
        assert "atempo=2.0" in chain

    def test_extreme_speed_chaining(self, simple_timeline, draft_preset):
        """Test chained atempo filters for extreme speeds."""
        clip = simple_timeline.find_clips()[0]
        asset_id = str(clip.media_reference.asset_id)
        asset_map = {asset_id: "/inputs/clip1.mp4"}

        converter = TimelineToFFmpeg(
            simple_timeline, asset_map, draft_preset, "/outputs/render.mp4"
        )

        # 4x speed requires chaining (atempo max is 2.0)
        chain = converter._build_atempo_chain(4.0)
        assert len(chain) >= 2  # Needs at least 2 atempo filters
        assert all("atempo=" in f for f in chain)
