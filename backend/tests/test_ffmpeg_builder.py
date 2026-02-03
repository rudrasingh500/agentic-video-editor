import pytest
from uuid import uuid4

from models.timeline_models import (
    Clip,
    Effect,
    ExternalReference,
    FreezeFrame,
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


@pytest.fixture
def sample_asset_map() -> dict[str, str]:
    return {
        "asset-1": "/inputs/project/videos/clip1.mp4",
        "asset-2": "/inputs/project/videos/clip2.mp4",
        "asset-3": "/inputs/project/audio/music.mp3",
    }


@pytest.fixture
def draft_preset() -> RenderPreset:
    return RenderPreset.draft_preview()


@pytest.fixture
def standard_preset() -> RenderPreset:
    return RenderPreset.standard_export()


@pytest.fixture
def simple_timeline() -> Timeline:
    clip = Clip(
        name="Test Clip",
        media_reference=ExternalReference(
            asset_id=uuid4(),
            target_url="gs://bucket/clip1.mp4",
        ),
        source_range=TimeRange(
            start_time=RationalTime(value=0, rate=24),
            duration=RationalTime(value=120, rate=24),
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

    clip2 = Clip(
        name="Clip 2",
        media_reference=ExternalReference(
            asset_id=uuid4(),
            target_url="gs://bucket/clip2.mp4",
        ),
        source_range=TimeRange(
            start_time=RationalTime(value=24, rate=24),
            duration=RationalTime(value=72, rate=24),
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
            duration=RationalTime(value=24, rate=24),
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
    clip1 = Clip(
        name="Clip 1",
        media_reference=ExternalReference(
            asset_id=uuid4(),
            target_url="gs://bucket/clip1.mp4",
        ),
        source_range=TimeRange(
            start_time=RationalTime(value=0, rate=24),
            duration=RationalTime(value=72, rate=24),
        ),
    )

    transition = Transition(
        name="Dissolve",
        transition_type=TransitionType.SMPTE_DISSOLVE,
        in_offset=RationalTime(value=12, rate=24),
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
            duration=RationalTime(value=72, rate=24),
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
                time_scalar=0.5,
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
def timeline_with_freeze_frame() -> Timeline:
    clip = Clip(
        name="Freeze Frame Clip",
        media_reference=ExternalReference(
            asset_id=uuid4(),
            target_url="gs://bucket/clip1.mp4",
        ),
        source_range=TimeRange(
            start_time=RationalTime(value=0, rate=24),
            duration=RationalTime(value=48, rate=24),
        ),
        effects=[FreezeFrame()],
    )

    video_track = Track(
        name="Video 1",
        kind=TrackKind.VIDEO,
        children=[clip],
    )

    return Timeline(
        name="Freeze Timeline",
        tracks=Stack(
            name="Timeline Stack",
            children=[video_track],
        ),
    )


@pytest.fixture
def timeline_with_generator() -> Timeline:
    generator_clip = Clip(
        name="Black Screen",
        media_reference=GeneratorReference(
            generator_kind="SolidColor",
            parameters={"color": "black"},
        ),
        source_range=TimeRange(
            start_time=RationalTime(value=0, rate=24),
            duration=RationalTime(value=48, rate=24),
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


class TestTimelineToFFmpeg:
    def test_collect_inputs_single_clip(self, simple_timeline, draft_preset):
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
        asset_map = {}

        converter = TimelineToFFmpeg(
            simple_timeline, asset_map, draft_preset, "/outputs/render.mp4"
        )
        converter._collect_inputs()

        assert len(converter._inputs) == 0
        assert "not found in asset_map" in caplog.text


class TestSegmentExtraction:
    def test_extract_clip_segment(self, simple_timeline, draft_preset):
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
        assert segments[0].duration == 5.0
        assert segments[0].is_gap is False

    def test_extract_gap_segment(self, timeline_with_gap, draft_preset):
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
        assert segments[1].duration == 1.0
        assert segments[2].is_gap is False

    def test_extract_speed_effect(self, timeline_with_speed_effect, draft_preset):
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

        assert segments[0].duration == 4.0


class TestFilterGeneration:
    def test_generate_trim_filter(self, simple_timeline, draft_preset):
        clip = simple_timeline.find_clips()[0]
        asset_id = str(clip.media_reference.asset_id)
        asset_map = {asset_id: "/inputs/clip1.mp4"}

        converter = TimelineToFFmpeg(
            simple_timeline, asset_map, draft_preset, "/outputs/render.mp4"
        )
        cmd = converter.build()

        assert "trim=" in cmd.filter_complex
        assert "setpts=PTS-STARTPTS" in cmd.filter_complex

    def test_generate_gap_video(self, timeline_with_gap, draft_preset):
        clips = timeline_with_gap.find_clips()
        asset_map = {}

        for clip in clips:
            asset_id = str(clip.media_reference.asset_id)
            asset_map[asset_id] = f"/inputs/{clip.name}.mp4"

        converter = TimelineToFFmpeg(
            timeline_with_gap, asset_map, draft_preset, "/outputs/render.mp4"
        )
        cmd = converter.build()

        assert "color=c=black" in cmd.filter_complex

    def test_generate_concat_filter(self, multi_clip_timeline, draft_preset):
        clips = multi_clip_timeline.find_clips()
        asset_map = {}

        for i, clip in enumerate(clips):
            asset_id = str(clip.media_reference.asset_id)
            asset_map[asset_id] = f"/inputs/clip{i + 1}.mp4"

        converter = TimelineToFFmpeg(
            multi_clip_timeline, asset_map, draft_preset, "/outputs/render.mp4"
        )
        cmd = converter.build()

        assert "concat=" in cmd.filter_complex

    def test_generate_transition_filter(self, timeline_with_transition, draft_preset):
        clips = timeline_with_transition.find_clips()
        asset_map = {}

        for i, clip in enumerate(clips):
            asset_id = str(clip.media_reference.asset_id)
            asset_map[asset_id] = f"/inputs/clip{i + 1}.mp4"

        converter = TimelineToFFmpeg(
            timeline_with_transition, asset_map, draft_preset, "/outputs/render.mp4"
        )
        cmd = converter.build()

        assert "xfade=" in cmd.filter_complex
        assert "dissolve" in cmd.filter_complex
        assert "offset=2.0" in cmd.filter_complex

    def test_generate_speed_filter(self, timeline_with_speed_effect, draft_preset):
        clip = timeline_with_speed_effect.find_clips()[0]
        asset_id = str(clip.media_reference.asset_id)
        asset_map = {asset_id: "/inputs/clip1.mp4"}

        converter = TimelineToFFmpeg(
            timeline_with_speed_effect, asset_map, draft_preset, "/outputs/render.mp4"
        )
        cmd = converter.build()

        assert "setpts=" in cmd.filter_complex

        assert "2.0*PTS" in cmd.filter_complex or "2*PTS" in cmd.filter_complex

    def test_generate_freeze_frame_filter(
        self, timeline_with_freeze_frame, draft_preset
    ):
        clip = timeline_with_freeze_frame.find_clips()[0]
        asset_id = str(clip.media_reference.asset_id)
        asset_map = {asset_id: "/inputs/clip1.mp4"}

        converter = TimelineToFFmpeg(
            timeline_with_freeze_frame, asset_map, draft_preset, "/outputs/render.mp4"
        )
        cmd = converter.build()

        assert "tpad=stop_mode=clone" in cmd.filter_complex
        assert "loop=loop=-1" not in cmd.filter_complex

    def test_position_normalized_coords(self, simple_timeline, draft_preset):
        clip = simple_timeline.find_clips()[0]
        clip.effects.append(
            Effect(
                effect_name="Position",
                metadata={
                    "type": "position",
                    "width": 0.5,
                    "height": 0.5,
                    "x": 0.25,
                    "y": 0.25,
                },
            )
        )
        asset_id = str(clip.media_reference.asset_id)
        asset_map = {asset_id: "/inputs/clip1.mp4"}

        converter = TimelineToFFmpeg(
            simple_timeline, asset_map, draft_preset, "/outputs/render.mp4"
        )
        cmd = converter.build()

        assert "scale=640:360" in cmd.filter_complex
        assert "pad=1280:720:320:180" in cmd.filter_complex

    def test_generate_solid_color(self, timeline_with_generator, draft_preset):
        converter = TimelineToFFmpeg(
            timeline_with_generator, {}, draft_preset, "/outputs/render.mp4"
        )
        cmd = converter.build()

        assert "color=c=black" in cmd.filter_complex


class TestOutputOptions:
    def test_cpu_encoding_options(self, simple_timeline):
        clip = simple_timeline.find_clips()[0]
        asset_id = str(clip.media_reference.asset_id)
        asset_map = {asset_id: "/inputs/clip1.mp4"}

        preset = RenderPreset.standard_export()

        converter = TimelineToFFmpeg(
            simple_timeline, asset_map, preset, "/outputs/render.mp4"
        )
        cmd = converter.build()

        assert "-c:v" in cmd.output_options
        assert "libx264" in cmd.output_options
        assert "-crf" in cmd.output_options

    def test_gpu_encoding_options(self, simple_timeline):
        clip = simple_timeline.find_clips()[0]
        asset_id = str(clip.media_reference.asset_id)
        asset_map = {asset_id: "/inputs/clip1.mp4"}

        preset = RenderPreset.high_quality_export()

        converter = TimelineToFFmpeg(
            simple_timeline, asset_map, preset, "/outputs/render.mp4"
        )
        cmd = converter.build()

        assert "-c:v" in cmd.output_options
        assert "h264_nvenc" in cmd.output_options
        assert "-cq" in cmd.output_options

    def test_audio_encoding_options(self, simple_timeline, draft_preset):
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
    def test_build_command_string(self, simple_timeline, draft_preset):
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
        clip = simple_timeline.find_clips()[0]
        asset_id = str(clip.media_reference.asset_id)
        asset_map = {asset_id: "/inputs/clip1.mp4"}

        timeline_dict = simple_timeline.model_dump()

        cmd_str = build_render_command(
            timeline_dict, asset_map, draft_preset, "/outputs/render.mp4"
        )

        assert cmd_str.startswith("ffmpeg -y")


class TestDurationEstimation:
    def test_estimate_cpu_duration(self, simple_timeline):
        preset = RenderPreset.standard_export()

        estimated = estimate_render_duration(simple_timeline, preset)

        assert estimated >= 5.0
        assert estimated <= 30.0

    def test_estimate_gpu_duration(self, simple_timeline):
        preset = RenderPreset.high_quality_export()

        estimated = estimate_render_duration(simple_timeline, preset)

        assert estimated >= 0.5
        assert estimated <= 5.0


class TestRenderPresets:
    def test_draft_preview_preset(self):
        preset = RenderPreset.draft_preview()

        assert preset.quality.value == "draft"
        assert preset.video.width == 1280
        assert preset.video.height == 720
        assert preset.video.crf == 28
        assert preset.video.preset == "veryfast"
        assert preset.use_gpu is False

    def test_standard_export_preset(self):
        preset = RenderPreset.standard_export()

        assert preset.quality.value == "standard"
        assert preset.video.crf == 23
        assert preset.video.preset == "medium"
        assert preset.use_gpu is False

    def test_high_quality_preset(self):
        preset = RenderPreset.high_quality_export()

        assert preset.quality.value == "high"
        assert preset.video.crf == 18
        assert preset.video.preset == "slow"
        assert preset.use_gpu is True

    def test_maximum_quality_preset(self):
        preset = RenderPreset.maximum_quality_export()

        assert preset.quality.value == "maximum"
        assert preset.video.crf == 15
        assert preset.video.preset == "veryslow"
        assert preset.use_gpu is True


class TestAtempoChain:
    def test_normal_speed(self, simple_timeline, draft_preset):
        clip = simple_timeline.find_clips()[0]
        asset_id = str(clip.media_reference.asset_id)
        asset_map = {asset_id: "/inputs/clip1.mp4"}

        converter = TimelineToFFmpeg(
            simple_timeline, asset_map, draft_preset, "/outputs/render.mp4"
        )

        chain = converter._build_atempo_chain(1.0)
        assert chain == []

    def test_half_speed(self, simple_timeline, draft_preset):
        clip = simple_timeline.find_clips()[0]
        asset_id = str(clip.media_reference.asset_id)
        asset_map = {asset_id: "/inputs/clip1.mp4"}

        converter = TimelineToFFmpeg(
            simple_timeline, asset_map, draft_preset, "/outputs/render.mp4"
        )

        chain = converter._build_atempo_chain(0.5)
        assert "atempo=0.5" in chain

    def test_double_speed(self, simple_timeline, draft_preset):
        clip = simple_timeline.find_clips()[0]
        asset_id = str(clip.media_reference.asset_id)
        asset_map = {asset_id: "/inputs/clip1.mp4"}

        converter = TimelineToFFmpeg(
            simple_timeline, asset_map, draft_preset, "/outputs/render.mp4"
        )

        chain = converter._build_atempo_chain(2.0)
        assert "atempo=2.0" in chain

    def test_extreme_speed_chaining(self, simple_timeline, draft_preset):
        clip = simple_timeline.find_clips()[0]
        asset_id = str(clip.media_reference.asset_id)
        asset_map = {asset_id: "/inputs/clip1.mp4"}

        converter = TimelineToFFmpeg(
            simple_timeline, asset_map, draft_preset, "/outputs/render.mp4"
        )

        chain = converter._build_atempo_chain(4.0)
        assert len(chain) >= 2
        assert all("atempo=" in f for f in chain)
