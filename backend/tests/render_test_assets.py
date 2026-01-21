from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4


ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"
RENDER_JOB_DIR = ROOT_DIR / "render-job"

sys.path.insert(0, str(RENDER_JOB_DIR))

from ffmpeg_renderer import FFmpegRenderer

try:
    from imageio_ffmpeg import get_ffmpeg_exe
except ImportError:  # pragma: no cover - optional dependency
    get_ffmpeg_exe = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render test assets with effects")
    parser.add_argument(
        "--asset",
        default="",
        help="Optional asset filename from backend/test_assets",
    )
    parser.add_argument(
        "--output-dir",
        default=str(BACKEND_DIR / "test_outputs"),
        help="Directory for rendered outputs",
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=24.0,
        help="Timeline framerate",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=8.0,
        help="Max duration to render in seconds",
    )
    parser.add_argument(
        "--use-gpu",
        action="store_true",
        help="Use GPU encoding (NVENC)",
    )
    parser.add_argument(
        "--ffmpeg",
        default=os.environ.get("FFMPEG_BIN", ""),
        help="Path to ffmpeg binary (optional)",
    )
    parser.add_argument(
        "--ffprobe",
        default=os.environ.get("FFPROBE_BIN", ""),
        help="Path to ffprobe binary (optional)",
    )
    return parser.parse_args()


def resolve_binary(name: str, override: str, allow_imageio: bool = True) -> str | None:
    if override:
        override_path = Path(override)
        if override_path.exists():
            return str(override_path)
        found = shutil.which(override)
        if found:
            return found
    if name == "ffmpeg" and allow_imageio and get_ffmpeg_exe:
        return get_ffmpeg_exe()
    return shutil.which(name)


def resolve_ffprobe(ffmpeg_bin: str | None, override: str) -> str | None:
    resolved = resolve_binary("ffprobe", override)
    if resolved:
        return resolved
    if ffmpeg_bin:
        suffix = ".exe" if os.name == "nt" else ""
        candidate = Path(ffmpeg_bin).with_name(f"ffprobe{suffix}")
        if candidate.exists():
            return str(candidate)
    return None


def ffmpeg_supports_nvenc(ffmpeg_bin: str) -> bool:
    try:
        result = subprocess.run(
            [ffmpeg_bin, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False

    output = result.stdout.lower()
    return "h264_nvenc" in output or "hevc_nvenc" in output


def ffprobe_duration(path: Path, ffprobe_bin: str) -> float:
    cmd = [
        ffprobe_bin,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    duration = data.get("format", {}).get("duration")
    if duration is None:
        raise ValueError(f"Duration not found for {path}")
    return float(duration)


def slugify_filename(name: str) -> str:
    value = name.replace(" ", "_")
    return "".join(ch for ch in value if ch.isalnum() or ch in "-_.") or "asset"


def build_timeline_dict(
    asset_id: str, asset_name: str, duration_seconds: float, rate: float
) -> dict:
    duration_frames = int(round(duration_seconds * rate))
    source_range = {
        "OTIO_SCHEMA": "TimeRange.1",
        "start_time": {
            "OTIO_SCHEMA": "RationalTime.1",
            "value": 0,
            "rate": rate,
        },
        "duration": {
            "OTIO_SCHEMA": "RationalTime.1",
            "value": duration_frames,
            "rate": rate,
        },
    }

    effects = [
        {
            "OTIO_SCHEMA": "Effect.1",
            "effect_name": "ColorGrade",
            "metadata": {
                "type": "grade",
                "brightness": 0.02,
                "contrast": 1.08,
                "saturation": 1.1,
            },
        },
        {
            "OTIO_SCHEMA": "Effect.1",
            "effect_name": "Curves",
            "metadata": {
                "type": "curves",
                "preset": "medium_contrast",
            },
        },
        {
            "OTIO_SCHEMA": "Effect.1",
            "effect_name": "Vignette",
            "metadata": {"type": "vignette", "strength": 0.45},
        },
        {
            "OTIO_SCHEMA": "Effect.1",
            "effect_name": "Grain",
            "metadata": {"type": "grain", "amount": 0.15},
        },
        {
            "OTIO_SCHEMA": "Effect.1",
            "effect_name": "Zoom",
            "metadata": {
                "type": "zoom",
                "start_zoom": 1.0,
                "end_zoom": 1.08,
                "center_x": 0.5,
                "center_y": 0.5,
            },
        },
    ]

    main_clip = {
        "OTIO_SCHEMA": "Clip.1",
        "name": asset_name,
        "source_range": source_range,
        "media_reference": {
            "OTIO_SCHEMA": "ExternalReference.1",
            "asset_id": asset_id,
            "metadata": {},
        },
        "effects": effects,
        "markers": [],
        "metadata": {},
    }

    caption_clip = {
        "OTIO_SCHEMA": "Clip.1",
        "name": "Caption Overlay",
        "source_range": source_range,
        "media_reference": {
            "OTIO_SCHEMA": "GeneratorReference.1",
            "generator_kind": "caption",
            "parameters": {
                "text": "Caption test overlay",
                "size": 48,
                "color": "white",
                "bg_color": "black@0.4",
                "x": "(w-text_w)/2",
                "y": "h-140",
            },
        },
        "effects": [],
        "markers": [],
        "metadata": {},
    }

    return {
        "OTIO_SCHEMA": "Timeline.1",
        "name": f"Test Timeline {asset_name}",
        "global_start_time": None,
        "tracks": {
            "OTIO_SCHEMA": "Stack.1",
            "name": "tracks",
            "children": [
                {
                    "OTIO_SCHEMA": "Track.1",
                    "name": "Video",
                    "kind": "Video",
                    "children": [main_clip],
                    "metadata": {},
                },
                {
                    "OTIO_SCHEMA": "Track.1",
                    "name": "Captions",
                    "kind": "Video",
                    "children": [caption_clip],
                    "metadata": {},
                },
            ],
            "metadata": {},
        },
        "metadata": {"default_rate": rate},
    }


def main() -> None:
    args = parse_args()

    ffmpeg_bin = resolve_binary("ffmpeg", args.ffmpeg, allow_imageio=not args.use_gpu)
    ffprobe_bin = resolve_ffprobe(ffmpeg_bin, args.ffprobe)
    if not ffmpeg_bin:
        print("ffmpeg not found on PATH.")
        print("Install FFmpeg or pass --ffmpeg with an explicit path.")
        raise SystemExit(1)
    if args.use_gpu and not ffmpeg_supports_nvenc(ffmpeg_bin):
        print("Requested GPU render, but ffmpeg does not expose NVENC encoders.")
        print("Install an ffmpeg build with NVENC, or pass --ffmpeg with a GPU build.")
        raise SystemExit(1)
    if not ffprobe_bin:
        print("ffprobe not found; falling back to ffmpeg for probing.")
        ffprobe_bin = ffmpeg_bin

    os.environ["FFMPEG_BIN"] = ffmpeg_bin
    os.environ["FFPROBE_BIN"] = ffprobe_bin

    assets_dir = BACKEND_DIR / "test_assets"
    if not assets_dir.exists():
        raise SystemExit(f"Test assets not found: {assets_dir}")

    assets = sorted(assets_dir.glob("*.mp4"))
    if not assets:
        raise SystemExit(f"No .mp4 assets found in {assets_dir}")

    if args.asset:
        asset_path = assets_dir / args.asset
        if not asset_path.exists():
            raise SystemExit(f"Asset not found: {asset_path}")
    else:
        asset_path = assets[0]

    try:
        duration = ffprobe_duration(asset_path, ffprobe_bin)
        duration = min(duration, max(args.duration, 1.0))
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(f"ffprobe unavailable ({exc}); using --duration value")
        duration = max(args.duration, 1.0)
    asset_id = str(uuid4())

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_name = f"render_test_{slugify_filename(asset_path.stem)}.mp4"
    output_path = output_dir / output_name

    timeline = build_timeline_dict(asset_id, asset_path.name, duration, args.rate)
    manifest = {
        "job_id": str(uuid4()),
        "project_id": "local-test",
        "timeline_version": 1,
        "timeline_snapshot": timeline,
        "asset_map": {asset_id: str(asset_path)},
        "preset": {
            "video": {
                "codec": "h264",
                "crf": 23,
                "preset": "veryfast",
                "pixel_format": "yuv420p",
                "width": 1920,
                "height": 1080,
                "framerate": args.rate,
            },
            "audio": {
                "codec": "aac",
                "bitrate": "192k",
                "sample_rate": 48000,
                "channels": 2,
            },
            "use_gpu": args.use_gpu,
        },
        "input_bucket": "local",
        "output_bucket": "local",
        "output_path": str(output_path),
    }

    renderer = FFmpegRenderer(manifest)
    output_info = renderer.render()

    print("Render complete")
    print(f"Output path: {output_info.get('output_path')}")
    print(f"Output url: {output_info.get('output_url')}")


if __name__ == "__main__":
    main()
