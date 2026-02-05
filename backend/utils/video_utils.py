"""Utilities for video processing operations."""
from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Maximum duration in seconds that Gemini can process (~40 minutes)
MAX_VIDEO_DURATION_SECONDS = 2400


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
