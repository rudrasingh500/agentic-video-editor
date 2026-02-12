"""Utilities for video processing operations."""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Maximum duration in seconds that Gemini can process (~40 minutes)
MAX_VIDEO_DURATION_SECONDS = 2400
MAX_EMBED_VIDEO_BYTES = int(os.getenv("MAX_EMBED_VIDEO_BYTES", "20000000"))


def extract_video_segment(
    input_bytes: bytes,
    start_seconds: float,
    duration_seconds: float,
    content_type: str = "video/mp4",
) -> bytes | None:
    """
    Extract a segment from a video using ffmpeg.

    Args:
        input_bytes: The input video as bytes
        start_seconds: Start time in seconds
        duration_seconds: Duration to extract in seconds
        content_type: The video MIME type

    Returns:
        The extracted segment as bytes, or None if extraction fails
    """
    ext_map = {
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "video/quicktime": ".mov",
        "video/x-msvideo": ".avi",
        "video/mpeg": ".mpg",
    }
    ext = ext_map.get(content_type, ".mp4")

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / f"input{ext}"
            output_path = Path(tmpdir) / f"output{ext}"

            input_path.write_bytes(input_bytes)

            cmd = [
                "ffmpeg",
                "-y",
                "-ss",
                str(start_seconds),
                "-i",
                str(input_path),
                "-t",
                str(duration_seconds),
                "-c",
                "copy",
                "-avoid_negative_ts",
                "make_zero",
                str(output_path),
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=120,
            )

            if result.returncode != 0:
                logger.error(
                    f"ffmpeg segment extraction failed: {result.stderr.decode()}"
                )
                return None

            if not output_path.exists():
                logger.error("ffmpeg output file not created")
                return None

            return output_path.read_bytes()

    except subprocess.TimeoutExpired:
        logger.error("ffmpeg segment extraction timed out")
        return None
    except Exception as e:
        logger.error(f"Segment extraction error: {e}")
        return None


def get_video_duration(
    input_bytes: bytes, content_type: str = "video/mp4"
) -> float | None:
    """
    Get the duration of a video in seconds using ffprobe.

    Args:
        input_bytes: The video as bytes
        content_type: The video MIME type

    Returns:
        Duration in seconds, or None if detection fails
    """
    ext_map = {
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "video/quicktime": ".mov",
        "video/x-msvideo": ".avi",
        "video/mpeg": ".mpg",
    }
    ext = ext_map.get(content_type, ".mp4")

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / f"input{ext}"
            input_path.write_bytes(input_bytes)

            cmd = [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(input_path),
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                return None

            return float(result.stdout.strip())

    except (subprocess.TimeoutExpired, ValueError, Exception):
        return None


def downscale_video_for_embedding(
    input_bytes: bytes,
    content_type: str = "video/mp4",
    max_bytes: int = MAX_EMBED_VIDEO_BYTES,
) -> bytes:
    """Downscale/re-encode video bytes to keep inline payloads smaller."""
    if not input_bytes or len(input_bytes) <= max_bytes:
        return input_bytes

    ext_map = {
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "video/quicktime": ".mov",
        "video/x-msvideo": ".avi",
        "video/mpeg": ".mpg",
    }
    ext = ext_map.get(content_type, ".mp4")
    ffmpeg_bin = os.getenv("FFMPEG_BIN", "ffmpeg")

    # (height, crf, audio_bitrate)
    passes: list[tuple[int, int, str]] = [
        (480, 28, "64k"),
        (360, 34, "48k"),
        (240, 38, "32k"),
    ]

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / f"input{ext}"
            input_path.write_bytes(input_bytes)

            best_output: bytes | None = None
            best_size = len(input_bytes)

            for idx, (height, crf, audio_bitrate) in enumerate(passes):
                output_path = Path(tmpdir) / f"downscaled_{idx}.mp4"
                cmd = [
                    ffmpeg_bin,
                    "-y",
                    "-i",
                    str(input_path),
                    "-vf",
                    f"scale=-2:{height}",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    str(crf),
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-b:a",
                    audio_bitrate,
                    "-movflags",
                    "+faststart",
                    str(output_path),
                ]

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=180,
                )

                if result.returncode != 0 or not output_path.exists():
                    logger.warning(
                        "Video downscale pass failed (h=%s, crf=%s): %s",
                        height,
                        crf,
                        result.stderr.decode(errors="ignore"),
                    )
                    continue

                output_bytes = output_path.read_bytes()
                output_size = len(output_bytes)

                if output_size < best_size:
                    best_output = output_bytes
                    best_size = output_size

                if output_size <= max_bytes:
                    logger.info(
                        "Video downscaled for embedding: %s -> %s bytes",
                        len(input_bytes),
                        output_size,
                    )
                    return output_bytes

            if best_output is not None and best_size < len(input_bytes):
                logger.info(
                    "Video downscaled (best effort) for embedding: %s -> %s bytes",
                    len(input_bytes),
                    best_size,
                )
                return best_output

    except subprocess.TimeoutExpired:
        logger.warning("Video downscale timed out for embedding")
    except Exception as exc:
        logger.warning("Video downscale failed for embedding: %s", exc)

    return input_bytes
