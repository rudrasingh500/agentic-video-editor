#!/usr/bin/env python3
import argparse
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from ffmpeg_renderer import FFmpegRenderer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render local test assets")
    parser.add_argument(
        "--input-dir",
        default=os.environ.get("RENDER_INPUT_DIR", ""),
        help="Directory containing test assets",
    )
    parser.add_argument(
        "--output-dir",
        default=os.environ.get("RENDER_OUTPUT_DIR", ""),
        help="Directory for rendered outputs",
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=24.0,
        help="Timeline framerate",
    )
    parser.add_argument(
        "--use-gpu",
        action="store_true",
        help="Use GPU encoding (auto-detect backend)",
    )
    parser.add_argument(
        "--gpu-backend",
        choices=["auto", "nvidia", "amd", "apple"],
        default="auto",
        help="Preferred GPU backend when --use-gpu is enabled",
    )
    return parser.parse_args()


@dataclass
class AssetInfo:
    asset_id: str
    path: Path
    duration_seconds: float


def slugify_filename(name: str) -> str:
    base = re.sub(r"\s+", "_", name.strip())
    base = re.sub(r"[^A-Za-z0-9._-]", "", base)
    return base or "asset"


def ffprobe_duration(path: Path) -> float:
    cmd = [
        "ffprobe",
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


def build_timeline_dict(asset: AssetInfo, rate: float) -> dict[str, Any]:
    duration_frames = int(round(asset.duration_seconds * rate))
    return {
        "OTIO_SCHEMA": "Timeline.1",
        "name": f"Test Timeline {asset.path.name}",
        "global_start_time": None,
        "tracks": {
            "OTIO_SCHEMA": "Stack.1",
            "name": "tracks",
            "children": [
                {
                    "OTIO_SCHEMA": "Track.1",
                    "name": "Video",
                    "kind": "Video",
                    "children": [
                        {
                            "OTIO_SCHEMA": "Clip.1",
                            "name": asset.path.name,
                            "source_range": {
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
                            },
                            "media_reference": {
                                "OTIO_SCHEMA": "ExternalReference.1",
                                "asset_id": asset.asset_id,
                                "metadata": {},
                            },
                            "effects": [],
                            "markers": [],
                            "metadata": {},
                        }
                    ],
                    "metadata": {},
                }
            ],
            "metadata": {},
        },
        "metadata": {"default_rate": rate},
    }


def build_manifest(
    asset: AssetInfo,
    timeline: dict[str, Any],
    output_path: str,
    use_gpu: bool,
    gpu_backend: str | None,
) -> dict[str, Any]:
    return {
        "job_id": str(uuid4()),
        "project_id": "local",
        "timeline_version": 1,
        "timeline_snapshot": timeline,
        "asset_map": {asset.asset_id: str(asset.path)},
        "preset": {
            "name": "Local GPU" if use_gpu else "Local CPU",
            "quality": "standard",
            "video": {
                "codec": "h264",
                "width": None,
                "height": None,
                "framerate": None,
                "bitrate": None,
                "crf": 23,
                "preset": "medium",
                "pixel_format": "yuv420p",
            },
            "audio": {
                "codec": "aac",
                "bitrate": "192k",
                "sample_rate": 48000,
                "channels": 2,
            },
            "use_gpu": use_gpu,
            "gpu_backend": gpu_backend if use_gpu else None,
        },
        "input_bucket": "local",
        "output_bucket": "local",
        "execution_mode": "local",
        "output_path": output_path,
    }


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def load_assets(input_dir: Path) -> list[AssetInfo]:
    assets = []
    for path in sorted(input_dir.glob("*.mp4")):
        duration = ffprobe_duration(path)
        assets.append(
            AssetInfo(asset_id=str(uuid4()), path=path, duration_seconds=duration)
        )
    return assets


def render_asset(
    asset: AssetInfo,
    output_dir: Path,
    rate: float,
    use_gpu: bool,
    gpu_backend: str | None,
) -> tuple[Path, Path]:
    timeline = build_timeline_dict(asset, rate)
    output_filename = (
        f"{slugify_filename(asset.path.stem)}_{'gpu' if use_gpu else 'cpu'}.mp4"
    )
    output_path = output_dir / output_filename
    manifest = build_manifest(asset, timeline, str(output_path), use_gpu, gpu_backend)

    manifest_path = output_dir / f"{slugify_filename(asset.path.stem)}_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    renderer = FFmpegRenderer(manifest)
    renderer.render()
    return output_path, manifest_path


def main() -> None:
    args = parse_args()

    if not args.input_dir:
        raise SystemExit("--input-dir is required (or set RENDER_INPUT_DIR)")
    if not args.output_dir:
        raise SystemExit("--output-dir is required (or set RENDER_OUTPUT_DIR)")

    input_dir = Path(args.input_dir).resolve()
    output_dir = Path(args.output_dir).resolve()

    if not input_dir.exists():
        raise SystemExit(f"Input directory not found: {input_dir}")

    ensure_directory(output_dir)

    assets = load_assets(input_dir)
    if not assets:
        raise SystemExit(f"No .mp4 assets found in {input_dir}")

    gpu_backend = None if args.gpu_backend == "auto" else args.gpu_backend

    for asset in assets:
        output_path, manifest_path = render_asset(
            asset, output_dir, args.rate, args.use_gpu, gpu_backend
        )
        print(f"Rendered {asset.path.name} -> {output_path}")
        print(f"Manifest saved: {manifest_path}")


if __name__ == "__main__":
    main()
