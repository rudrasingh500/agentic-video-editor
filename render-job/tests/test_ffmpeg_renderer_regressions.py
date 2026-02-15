from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path

import pytest


RENDER_JOB_DIR = Path(__file__).resolve().parents[1]
if str(RENDER_JOB_DIR) not in sys.path:
    sys.path.insert(0, str(RENDER_JOB_DIR))


@pytest.fixture(scope="module")
def ffmpeg_renderer_module():
    original_graphics = sys.modules.get("graphics_generator")
    original_renderer = sys.modules.get("ffmpeg_renderer")

    fake_graphics = types.ModuleType("graphics_generator")

    class OverlayAsset:
        def __init__(
            self,
            path: str,
            fps: float,
            frame_count: int,
            duration: float,
            is_sequence: bool,
            start_number: int = 1,
        ):
            self.path = path
            self.fps = fps
            self.frame_count = frame_count
            self.duration = duration
            self.is_sequence = is_sequence
            self.start_number = start_number

    class OverlayGenerator:
        def __init__(self, *args, **kwargs):
            pass

        def generate(self, *args, **kwargs):
            return OverlayAsset(
                path="/tmp/overlay.png",
                fps=24.0,
                frame_count=1,
                duration=0.1,
                is_sequence=False,
            )

    setattr(fake_graphics, "OverlayAsset", OverlayAsset)
    setattr(fake_graphics, "OverlayGenerator", OverlayGenerator)

    sys.modules["graphics_generator"] = fake_graphics
    sys.modules.pop("ffmpeg_renderer", None)
    module = importlib.import_module("ffmpeg_renderer")
    yield module

    if original_graphics is not None:
        sys.modules["graphics_generator"] = original_graphics
    else:
        sys.modules.pop("graphics_generator", None)

    if original_renderer is not None:
        sys.modules["ffmpeg_renderer"] = original_renderer
    else:
        sys.modules.pop("ffmpeg_renderer", None)


def _manifest() -> dict[str, object]:
    return {
        "job_id": "job-1",
        "project_id": "project-1",
        "timeline_version": 1,
        "timeline_snapshot": {"tracks": {"children": []}},
        "asset_map": {},
        "preset": {"video": {}, "audio": {}},
        "input_bucket": "input-bucket",
        "output_bucket": "local",
        "output_path": "render.mp4",
    }


@pytest.mark.parametrize("stream_types", [{"audio"}, {"a"}])
def test_process_audio_segment_accepts_audio_stream_labels(
    ffmpeg_renderer_module,
    stream_types: set[str],
):
    converter = ffmpeg_renderer_module.TimelineToFFmpeg(
        timeline={"tracks": {"children": []}},
        asset_map={},
        preset={"audio": {"sample_rate": 48000, "channels": 2}},
        input_streams={0: stream_types},
    )
    segment = ffmpeg_renderer_module.TrackSegment(
        start_time=0.0,
        duration=2.0,
        source_start=0.0,
        source_duration=2.0,
        input_index=0,
    )

    label = converter._process_audio_segment(segment, 0, 0)

    assert label == "a0_0"
    assert any("atrim=" in entry for entry in converter._audio_filters)
    assert not any("anullsrc=" in entry for entry in converter._audio_filters)


def test_process_audio_segment_generates_silence_when_no_audio(ffmpeg_renderer_module):
    converter = ffmpeg_renderer_module.TimelineToFFmpeg(
        timeline={"tracks": {"children": []}},
        asset_map={},
        preset={"audio": {"sample_rate": 48000, "channels": 2}},
        input_streams={0: {"video"}},
    )
    segment = ffmpeg_renderer_module.TrackSegment(
        start_time=0.0,
        duration=2.0,
        source_start=0.0,
        source_duration=2.0,
        input_index=0,
    )

    label = converter._process_audio_segment(segment, 0, 0)

    assert label == "a0_0"
    assert any("anullsrc=" in entry for entry in converter._audio_filters)


def test_probe_streams_normalizes_ffprobe_codec_types(monkeypatch, ffmpeg_renderer_module, tmp_path):
    monkeypatch.setenv("RENDER_TEMP_DIR", str(tmp_path))
    renderer = ffmpeg_renderer_module.FFmpegRenderer(_manifest())

    class Completed:
        def __init__(self, stdout: str = "", stderr: str = ""):
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(cmd, capture_output, text, check=False):
        return Completed(
            stdout=json.dumps(
                {
                    "streams": [
                        {"codec_type": "video"},
                        {"codec_type": "audio"},
                        {"codec_type": "subtitle"},
                    ]
                }
            )
        )

    monkeypatch.setattr(ffmpeg_renderer_module.subprocess, "run", fake_run)

    streams = renderer._probe_streams({"asset-1": "clip.mp4"})

    assert streams == {0: {"v", "a"}}


def test_probe_streams_fallback_normalizes_ffmpeg_output(monkeypatch, ffmpeg_renderer_module, tmp_path):
    monkeypatch.setenv("RENDER_TEMP_DIR", str(tmp_path))
    renderer = ffmpeg_renderer_module.FFmpegRenderer(_manifest())

    class Completed:
        def __init__(self, stdout: str = "", stderr: str = ""):
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(cmd, capture_output, text, check=False):
        if "-show_entries" in cmd:
            raise ffmpeg_renderer_module.subprocess.CalledProcessError(1, cmd)
        return Completed(
            stderr=(
                "Stream #0:0: Video: h264 (High), yuv420p\n"
                "Stream #0:1: Audio: aac (LC), 48000 Hz\n"
            )
        )

    monkeypatch.setattr(ffmpeg_renderer_module.subprocess, "run", fake_run)

    streams = renderer._probe_streams({"asset-1": "clip.mp4"})

    assert streams == {0: {"v", "a"}}


def test_effect_asset_cache_paths_avoid_filename_collisions(
    monkeypatch,
    ffmpeg_renderer_module,
    tmp_path,
):
    monkeypatch.setenv("RENDER_TEMP_DIR", str(tmp_path))
    renderer = ffmpeg_renderer_module.FFmpegRenderer(_manifest())

    downloads: list[tuple[str, str, str]] = []

    def fake_download(bucket_name: str, blob_path: str, local_path: Path) -> None:
        downloads.append((bucket_name, blob_path, str(local_path)))
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text(f"{bucket_name}/{blob_path}", encoding="utf-8")

    monkeypatch.setattr(renderer, "_download_asset", fake_download)

    first = renderer._download_effect_asset("gs://video-editor/effects/set-a/logo.png")
    second = renderer._download_effect_asset("gs://video-editor/effects/set-b/logo.png")
    first_again = renderer._download_effect_asset("gs://video-editor/effects/set-a/logo.png")

    assert first != second
    assert first_again == first
    assert len(downloads) == 2
    assert Path(first).exists()
    assert Path(second).exists()
