from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import cv2
import numpy as np


def resolve_frame_indices(
    total_frames: int,
    frame_range: dict[str, Any] | None,
    frame_indices: list[int] | None,
) -> list[int]:
    candidates: set[int] = set()

    if frame_indices:
        for value in frame_indices:
            idx = int(value)
            if 0 <= idx < total_frames:
                candidates.add(idx)

    if frame_range:
        start = int(frame_range.get("start_frame", 0))
        end = int(frame_range.get("end_frame", start))
        if end < start:
            start, end = end, start
        start = max(0, start)
        end = min(total_frames - 1, end)
        if start <= end:
            for idx in range(start, end + 1):
                candidates.add(idx)

    return sorted(candidates)


def apply_frame_edit(
    target_video_bytes: bytes,
    target_content_type: str,
    generated_frame_bytes: bytes,
    mode: str,
    frame_range: dict[str, Any] | None = None,
    frame_indices: list[int] | None = None,
    frame_repeat_count: int = 1,
) -> tuple[bytes, str, dict[str, Any]]:
    if not target_content_type.startswith("video/"):
        raise ValueError("target asset must be a video")

    if mode not in {"replace_frames", "insert_frames"}:
        raise ValueError(f"Unsupported frame edit mode: {mode}")

    repeat_count = int(frame_repeat_count or 1)
    if repeat_count < 1:
        raise ValueError("frame_repeat_count must be >= 1")

    decoded = cv2.imdecode(np.frombuffer(generated_frame_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if decoded is None:
        raise ValueError("Generated frame asset is not a valid image")

    with tempfile.TemporaryDirectory() as tmpdir:
        temp_dir = Path(tmpdir)
        input_path = temp_dir / "input.mp4"
        silent_output_path = temp_dir / "edited_no_audio.mp4"
        muxed_output_path = temp_dir / "edited_with_audio.mp4"

        input_path.write_bytes(target_video_bytes)

        capture = cv2.VideoCapture(str(input_path))
        if not capture.isOpened():
            raise RuntimeError("Failed to decode target video")

        try:
            fps = float(capture.get(cv2.CAP_PROP_FPS) or 24.0)
            if fps <= 0:
                fps = 24.0
            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            if width <= 0 or height <= 0:
                raise RuntimeError("Target video has invalid frame dimensions")
            if total_frames <= 0:
                raise RuntimeError("Target video has no readable frames")

            selected_indices = resolve_frame_indices(
                total_frames=total_frames,
                frame_range=frame_range,
                frame_indices=frame_indices,
            )
            if not selected_indices:
                raise ValueError("No valid frame indices were resolved for editing")

            replace_indices = _expand_replace_indices(
                selected_indices=selected_indices,
                total_frames=total_frames,
                frame_repeat_count=repeat_count,
            )

            replacement_frame = cv2.resize(decoded, (width, height), interpolation=cv2.INTER_AREA)
            selected_set = set(selected_indices)
            replace_set = set(replace_indices)

            writer = cv2.VideoWriter(
                str(silent_output_path),
                cv2.VideoWriter_fourcc(*"mp4v"),
                fps,
                (width, height),
            )
            if not writer.isOpened():
                raise RuntimeError("Failed to create output video writer")

            input_frames_read = 0
            written_frames = 0
            while True:
                ok, frame = capture.read()
                if not ok:
                    break

                current_frame_index = input_frames_read
                if mode == "replace_frames":
                    writer.write(
                        replacement_frame if current_frame_index in replace_set else frame
                    )
                    written_frames += 1
                else:
                    writer.write(frame)
                    written_frames += 1
                    if current_frame_index in selected_set:
                        for _ in range(repeat_count):
                            writer.write(replacement_frame)
                            written_frames += 1

                input_frames_read += 1

            writer.release()

            if input_frames_read <= 0 or written_frames <= 0:
                raise RuntimeError("Frame edit produced no output frames")

        finally:
            capture.release()

        output_path = silent_output_path
        if _mux_audio_track(input_path, silent_output_path, muxed_output_path):
            output_path = muxed_output_path

        validated_frames, validated_fps = _validate_video_output(output_path)
        if validated_frames <= 0:
            raise RuntimeError("Generated video has zero readable frames")

        edited_bytes = output_path.read_bytes()
        output_frames = validated_frames

    metadata = {
        "mode": mode,
        "input_frame_count": total_frames,
        "input_frames_read": input_frames_read,
        "output_frame_count": output_frames,
        "written_frame_count": written_frames,
        "frame_repeat_count": repeat_count,
        "selected_frame_indices": selected_indices,
        "effective_replaced_frame_indices": replace_indices if mode == "replace_frames" else [],
        "fps": validated_fps,
        "output_duration_seconds": (
            round(output_frames / validated_fps, 6) if validated_fps > 0 else None
        ),
        "width": width,
        "height": height,
    }
    return edited_bytes, "video/mp4", metadata


def _expand_replace_indices(
    selected_indices: list[int],
    total_frames: int,
    frame_repeat_count: int,
) -> list[int]:
    if frame_repeat_count <= 1:
        return sorted({idx for idx in selected_indices if 0 <= idx < total_frames})

    expanded: set[int] = set()
    for idx in selected_indices:
        for offset in range(frame_repeat_count):
            candidate = idx + offset
            if 0 <= candidate < total_frames:
                expanded.add(candidate)
    return sorted(expanded)


def _validate_video_output(video_path: Path) -> tuple[int, float]:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        return 0, 0.0
    try:
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        if frame_count <= 0:
            readable = 0
            while True:
                ok, _ = capture.read()
                if not ok:
                    break
                readable += 1
            frame_count = readable
        if fps <= 0:
            fps = 24.0
        return frame_count, fps
    finally:
        capture.release()


def _mux_audio_track(
    input_path: Path,
    silent_video_path: Path,
    output_path: Path,
) -> bool:
    ffmpeg_bin = os.getenv("FFMPEG_BIN", "ffmpeg")

    web_compatible = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(silent_video_path),
        "-i",
        str(input_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a?",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        "-shortest",
        str(output_path),
    ]
    try:
        result = subprocess.run(web_compatible, capture_output=True, text=True, timeout=180)
        if result.returncode == 0 and output_path.exists():
            return True
    except Exception:
        return False

    command = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(silent_video_path),
        "-i",
        str(input_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a?",
        "-c:v",
        "copy",
        "-c:a",
        "copy",
        "-shortest",
        str(output_path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        if result.returncode == 0 and output_path.exists():
            return True
    except Exception:
        return False

    fallback = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(silent_video_path),
        "-i",
        str(input_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a?",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-shortest",
        str(output_path),
    ]
    try:
        result = subprocess.run(fallback, capture_output=True, text=True, timeout=120)
        return result.returncode == 0 and output_path.exists()
    except Exception:
        return False
