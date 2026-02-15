#!/usr/bin/env python3
import argparse
import json
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

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
        "name": f"QA Timeline {asset.path.name}",
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


@dataclass
class QAPreset:
    profile_id: str
    description: str
    preset: dict[str, Any]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render QA matrix for codec/preset benchmarking"
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Input file or directory with .mp4 assets",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory where QA renders and reports are written",
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=24.0,
        help="Timeline framerate",
    )
    parser.add_argument(
        "--assets-limit",
        type=int,
        default=3,
        help="Maximum number of input assets to benchmark",
    )
    parser.add_argument(
        "--profiles",
        default="",
        help="Comma-separated profile IDs to run (default: run all)",
    )
    parser.add_argument(
        "--use-gpu",
        action="store_true",
        help="Use GPU for h264/h265 profiles when available",
    )
    parser.add_argument(
        "--gpu-backend",
        choices=["auto", "nvidia", "amd", "apple"],
        default="auto",
        help="Preferred GPU backend when --use-gpu is enabled",
    )
    parser.add_argument(
        "--quality-metrics",
        action="store_true",
        help="Compute optional SSIM/PSNR against source",
    )
    parser.add_argument(
        "--ffmpeg-bin",
        default="ffmpeg",
        help="Path to ffmpeg binary",
    )
    parser.add_argument(
        "--ffprobe-bin",
        default="ffprobe",
        help="Path to ffprobe binary",
    )
    return parser.parse_args()


def discover_assets(input_path: Path, limit: int) -> list[AssetInfo]:
    files: list[Path]
    if input_path.is_file():
        files = [input_path]
    else:
        files = sorted(input_path.glob("*.mp4"))

    assets: list[AssetInfo] = []
    for path in files[: max(1, limit)]:
        duration = ffprobe_duration(path)
        assets.append(
            AssetInfo(asset_id=str(uuid4()), path=path, duration_seconds=duration)
        )
    return assets


def qa_profiles(use_gpu: bool, gpu_backend: str | None) -> list[QAPreset]:
    gpu_backend_value = gpu_backend if use_gpu else None
    return [
        QAPreset(
            profile_id="draft_h264",
            description="Fast draft profile",
            preset={
                "name": "QA Draft H264",
                "quality": "draft",
                "video": {
                    "codec": "h264",
                    "container": "mp4",
                    "width": 1280,
                    "height": 720,
                    "crf": 28,
                    "preset": "veryfast",
                    "bitrate": "3M",
                    "pixel_format": "yuv420p",
                    "two_pass": False,
                },
                "audio": {
                    "codec": "aac",
                    "bitrate": "128k",
                    "sample_rate": 48000,
                    "channels": 2,
                },
                "use_gpu": use_gpu,
                "gpu_backend": gpu_backend_value,
            },
        ),
        QAPreset(
            profile_id="standard_h264",
            description="Balanced delivery profile",
            preset={
                "name": "QA Standard H264",
                "quality": "standard",
                "video": {
                    "codec": "h264",
                    "container": "mp4",
                    "width": 1920,
                    "height": 1080,
                    "crf": 21,
                    "preset": "medium",
                    "bitrate": "8M",
                    "pixel_format": "yuv420p",
                    "two_pass": False,
                },
                "audio": {
                    "codec": "aac",
                    "bitrate": "192k",
                    "sample_rate": 48000,
                    "channels": 2,
                },
                "use_gpu": use_gpu,
                "gpu_backend": gpu_backend_value,
            },
        ),
        QAPreset(
            profile_id="high_h265_10bit",
            description="High quality 10-bit HEVC",
            preset={
                "name": "QA High H265",
                "quality": "high",
                "video": {
                    "codec": "h265",
                    "container": "mp4",
                    "crf": 17,
                    "preset": "slow",
                    "bitrate": "15M",
                    "pixel_format": "yuv420p10le",
                    "two_pass": False,
                },
                "audio": {
                    "codec": "aac",
                    "bitrate": "256k",
                    "sample_rate": 48000,
                    "channels": 2,
                },
                "use_gpu": use_gpu,
                "gpu_backend": gpu_backend_value,
            },
        ),
        QAPreset(
            profile_id="prores_hq",
            description="Editing master mezzanine",
            preset={
                "name": "QA ProRes HQ",
                "quality": "maximum",
                "video": {
                    "codec": "prores",
                    "container": "mov",
                    "bitrate": "110M",
                    "pixel_format": "yuv422p10le",
                    "two_pass": False,
                    "prores_profile": "hq",
                },
                "audio": {
                    "codec": "aac",
                    "bitrate": "320k",
                    "sample_rate": 48000,
                    "channels": 2,
                },
                "use_gpu": False,
            },
        ),
        QAPreset(
            profile_id="vp9_stream",
            description="Web VP9 stream profile",
            preset={
                "name": "QA VP9 Stream",
                "quality": "high",
                "video": {
                    "codec": "vp9",
                    "container": "webm",
                    "crf": 30,
                    "preset": "medium",
                    "bitrate": "8M",
                    "two_pass": True,
                },
                "audio": {
                    "codec": "opus",
                    "bitrate": "160k",
                    "sample_rate": 48000,
                    "channels": 2,
                },
                "use_gpu": False,
            },
        ),
        QAPreset(
            profile_id="av1_stream",
            description="Web AV1 stream profile",
            preset={
                "name": "QA AV1 Stream",
                "quality": "high",
                "video": {
                    "codec": "av1",
                    "container": "mkv",
                    "crf": 29,
                    "preset": "slow",
                    "bitrate": "6M",
                    "pixel_format": "yuv420p10le",
                    "two_pass": False,
                },
                "audio": {
                    "codec": "opus",
                    "bitrate": "160k",
                    "sample_rate": 48000,
                    "channels": 2,
                },
                "use_gpu": False,
            },
        ),
    ]


def output_extension_for_preset(preset: dict[str, Any]) -> str:
    video = preset.get("video", {})
    codec = str(video.get("codec", "h264")).lower()
    container = str(video.get("container", "")).lower()
    if container in {"mp4", "mov", "mkv", "webm"}:
        return container
    if codec == "prores":
        return "mov"
    if codec == "vp9":
        return "webm"
    if codec == "av1":
        return "mkv"
    return "mp4"


def build_manifest(
    asset: AssetInfo,
    timeline: dict[str, Any],
    preset: dict[str, Any],
    output_path: str,
) -> dict[str, Any]:
    return {
        "job_id": str(uuid4()),
        "project_id": "qa",
        "timeline_version": 1,
        "timeline_snapshot": timeline,
        "asset_map": {asset.asset_id: str(asset.path)},
        "preset": preset,
        "input_bucket": "local",
        "output_bucket": "local",
        "execution_mode": "local",
        "output_path": output_path,
        "output_variants": [],
    }


def ffprobe_file(path: Path, ffprobe_bin: str) -> dict[str, Any]:
    cmd = [
        ffprobe_bin,
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)

    streams = data.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})
    format_data = data.get("format", {})

    return {
        "container": format_data.get("format_name"),
        "duration": safe_float(format_data.get("duration")),
        "bit_rate": safe_int(format_data.get("bit_rate")),
        "size": safe_int(format_data.get("size")),
        "video_codec": video_stream.get("codec_name"),
        "video_profile": video_stream.get("profile"),
        "width": video_stream.get("width"),
        "height": video_stream.get("height"),
        "pix_fmt": video_stream.get("pix_fmt"),
        "avg_frame_rate": video_stream.get("avg_frame_rate"),
        "audio_codec": audio_stream.get("codec_name"),
        "audio_sample_rate": safe_int(audio_stream.get("sample_rate")),
        "audio_channels": audio_stream.get("channels"),
        "audio_bit_rate": safe_int(audio_stream.get("bit_rate")),
    }


def compute_quality_metrics(
    source_path: Path,
    output_path: Path,
    ffmpeg_bin: str,
) -> dict[str, float | None]:
    filter_graph = (
        "[0:v][1:v]scale2ref=flags=bicubic[dist][ref];"
        "[dist]split[dist1][dist2];"
        "[dist1][ref]ssim;"
        "[dist2][ref]psnr"
    )
    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-i",
        str(output_path),
        "-i",
        str(source_path),
        "-lavfi",
        filter_graph,
        "-an",
        "-f",
        "null",
        "-",
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {"ssim": None, "psnr": None}

    text = (result.stdout or "") + "\n" + (result.stderr or "")
    ssim_values = re.findall(r"All:([0-9.]+)", text)
    psnr_values = re.findall(r"average:([0-9.]+)", text)

    ssim = safe_float(ssim_values[-1]) if ssim_values else None
    psnr = safe_float(psnr_values[-1]) if psnr_values else None
    return {"ssim": ssim, "psnr": psnr}


def safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def render_matrix(
    assets: list[AssetInfo],
    profiles: list[QAPreset],
    output_dir: Path,
    rate: float,
    ffmpeg_bin: str,
    ffprobe_bin: str,
    quality_metrics: bool,
) -> list[dict[str, Any]]:
    from ffmpeg_renderer import FFmpegRenderer, RenderError

    results: list[dict[str, Any]] = []

    for asset in assets:
        timeline = build_timeline_dict(asset, rate)
        asset_slug = slugify_filename(asset.path.stem)

        for profile in profiles:
            ext = output_extension_for_preset(profile.preset)
            output_name = f"{asset_slug}_{profile.profile_id}.{ext}"
            output_path = output_dir / output_name

            manifest = build_manifest(
                asset=asset,
                timeline=timeline,
                preset=profile.preset,
                output_path=str(output_path),
            )

            start = time.perf_counter()
            error_text: str | None = None
            render_output: dict[str, Any] | None = None

            try:
                renderer = FFmpegRenderer(manifest)
                renderer._ffmpeg_bin = ffmpeg_bin
                renderer._ffprobe_bin = ffprobe_bin
                render_output = renderer.render()
            except RenderError as exc:
                error_text = str(exc)

            elapsed = time.perf_counter() - start

            probe: dict[str, Any] | None = None
            metrics: dict[str, float | None] | None = None
            if output_path.exists() and error_text is None:
                probe = ffprobe_file(output_path, ffprobe_bin)
                if quality_metrics:
                    metrics = compute_quality_metrics(asset.path, output_path, ffmpeg_bin)

            results.append(
                {
                    "asset_name": asset.path.name,
                    "asset_path": str(asset.path),
                    "profile_id": profile.profile_id,
                    "description": profile.description,
                    "preset": profile.preset,
                    "output_path": str(output_path),
                    "render_seconds": round(elapsed, 3),
                    "error": error_text,
                    "probe": probe,
                    "quality_metrics": metrics,
                    "renderer_output": render_output,
                }
            )

            status = "FAILED" if error_text else "OK"
            print(
                f"[{status}] {asset.path.name} -> {profile.profile_id} "
                f"({elapsed:.2f}s)"
            )
            if error_text:
                print(f"    Error: {error_text}")

    return results


def write_reports(results: list[dict[str, Any]], output_dir: Path) -> tuple[Path, Path]:
    report_json = output_dir / "qa_report.json"
    report_md = output_dir / "qa_report.md"

    summary = {
        "total_runs": len(results),
        "successes": sum(1 for r in results if not r.get("error")),
        "failures": sum(1 for r in results if r.get("error")),
    }

    payload = {
        "summary": summary,
        "results": results,
    }
    report_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines: list[str] = []
    lines.append("# Render QA Report")
    lines.append("")
    lines.append(f"- Total runs: {summary['total_runs']}")
    lines.append(f"- Successes: {summary['successes']}")
    lines.append(f"- Failures: {summary['failures']}")
    lines.append("")
    lines.append(
        "| Asset | Profile | Codec | Resolution | PixFmt | Size (MB) | Bitrate (kbps) | "
        "Render (s) | SSIM | PSNR | Status |"
    )
    lines.append("|---|---|---|---|---|---:|---:|---:|---:|---:|---|")

    for row in results:
        probe = row.get("probe") or {}
        metrics = row.get("quality_metrics") or {}
        status = "FAIL" if row.get("error") else "OK"

        width = probe.get("width")
        height = probe.get("height")
        resolution = f"{width}x{height}" if width and height else "-"

        size_bytes = probe.get("size")
        bitrate = probe.get("bit_rate")

        size_mb = f"{(size_bytes / (1024 * 1024)):.2f}" if size_bytes else "-"
        bitrate_kbps = f"{(bitrate / 1000):.0f}" if bitrate else "-"
        ssim = metrics.get("ssim")
        psnr = metrics.get("psnr")

        lines.append(
            "| "
            f"{row.get('asset_name', '-')} | "
            f"{row.get('profile_id', '-')} | "
            f"{probe.get('video_codec', '-')} | "
            f"{resolution} | "
            f"{probe.get('pix_fmt', '-')} | "
            f"{size_mb} | "
            f"{bitrate_kbps} | "
            f"{row.get('render_seconds', '-')} | "
            f"{f'{ssim:.4f}' if isinstance(ssim, float) else '-'} | "
            f"{f'{psnr:.2f}' if isinstance(psnr, float) else '-'} | "
            f"{status} |"
        )

    report_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_json, report_md


def main() -> None:
    args = parse_args()

    input_path = Path(args.input).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if not input_path.exists():
        raise SystemExit(f"Input path not found: {input_path}")

    assets = discover_assets(input_path, args.assets_limit)
    if not assets:
        raise SystemExit("No input assets found (.mp4)")

    gpu_backend = None if args.gpu_backend == "auto" else args.gpu_backend
    profiles = qa_profiles(use_gpu=args.use_gpu, gpu_backend=gpu_backend)

    if args.profiles:
        wanted = {part.strip() for part in args.profiles.split(",") if part.strip()}
        profiles = [profile for profile in profiles if profile.profile_id in wanted]
        if not profiles:
            raise SystemExit(
                "No matching profiles selected. "
                "Use --profiles with valid IDs: "
                "draft_h264,standard_h264,high_h265_10bit,prores_hq,vp9_stream,av1_stream"
            )

    print(f"Assets: {len(assets)}")
    print(f"Profiles: {len(profiles)}")
    print(f"Output directory: {output_dir}")

    results = render_matrix(
        assets=assets,
        profiles=profiles,
        output_dir=output_dir,
        rate=args.rate,
        ffmpeg_bin=args.ffmpeg_bin,
        ffprobe_bin=args.ffprobe_bin,
        quality_metrics=args.quality_metrics,
    )

    report_json, report_md = write_reports(results, output_dir)
    print(f"JSON report: {report_json}")
    print(f"Markdown report: {report_md}")


if __name__ == "__main__":
    main()
