#!/usr/bin/env python3
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("ffmpeg-renderer")


class RenderError(Exception):
    pass


@dataclass
class RenderManifest:
    job_id: str
    project_id: str
    timeline_version: int
    timeline_snapshot: dict[str, Any]
    asset_map: dict[str, str]
    preset: dict[str, Any]
    input_bucket: str
    output_bucket: str
    output_path: str
    start_frame: int | None = None
    end_frame: int | None = None
    callback_url: str | None = None


class FFmpegRenderer:
    def __init__(self, manifest_dict: dict[str, Any]):
        self.manifest = RenderManifest(
            job_id=manifest_dict["job_id"],
            project_id=manifest_dict["project_id"],
            timeline_version=manifest_dict["timeline_version"],
            timeline_snapshot=manifest_dict["timeline_snapshot"],
            asset_map=manifest_dict["asset_map"],
            preset=manifest_dict["preset"],
            input_bucket=manifest_dict["input_bucket"],
            output_bucket=manifest_dict["output_bucket"],
            output_path=manifest_dict["output_path"],
            start_frame=manifest_dict.get("start_frame"),
            end_frame=manifest_dict.get("end_frame"),
            callback_url=manifest_dict.get("callback_url"),
        )
        self.temp_dir = Path(os.environ.get("RENDER_TEMP_DIR", "/tmp/render"))
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        self.inputs_dir = Path("/inputs")
        self.outputs_dir = Path("/outputs")

    def render(
        self,
        progress_callback: Callable[[int, str | None], None] | None = None,
    ) -> str:
        logger.info(f"Starting render for job {self.manifest.job_id}")

        local_asset_map = self._resolve_asset_paths()

        if progress_callback:
            progress_callback(5, "Resolved asset paths")

        ffmpeg_cmd = self._build_ffmpeg_command(local_asset_map)

        if progress_callback:
            progress_callback(10, "Built FFmpeg command")

        logger.info(f"FFmpeg command: {' '.join(ffmpeg_cmd[:10])}...")

        output_path = self._execute_ffmpeg(ffmpeg_cmd, progress_callback)

        logger.info(f"Render complete: {output_path}")

        return output_path

    def _resolve_asset_paths(self) -> dict[str, str]:
        local_paths = {}

        for asset_id, gcs_path in self.manifest.asset_map.items():
            local_path = self.inputs_dir / gcs_path

            if not local_path.exists():
                raise RenderError(f"Asset not found: {gcs_path}")

            local_paths[asset_id] = str(local_path)
            logger.debug(f"Asset {asset_id}: {local_path}")

        return local_paths

    def _build_ffmpeg_command(self, asset_map: dict[str, str]) -> list[str]:
        timeline = self.manifest.timeline_snapshot
        preset = self.manifest.preset

        output_path = self.outputs_dir / self.manifest.output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = ["ffmpeg", "-y"]

        inputs, filter_complex, maps = self._build_filter_graph(timeline, asset_map)

        for input_file in inputs:
            cmd.extend(["-i", input_file])

        if filter_complex:
            cmd.extend(["-filter_complex", filter_complex])

        for m in maps:
            cmd.extend(["-map", m])

        cmd.extend(self._build_encoding_options(preset))

        cmd.append(str(output_path))

        return cmd

    def _build_filter_graph(
        self,
        timeline: dict[str, Any],
        asset_map: dict[str, str],
    ) -> tuple[list[str], str, list[str]]:
        inputs: list[str] = []
        filters: list[str] = []
        input_index_map: dict[str, int] = {}

        tracks = timeline.get("tracks", {})
        children = tracks.get("children", [])

        video_segments = []
        audio_segments = []

        for track in children:
            if track.get("OTIO_SCHEMA") != "Track.1":
                continue

            track_kind = track.get("kind", "Video")
            track_children = track.get("children", [])

            for item in track_children:
                if item.get("OTIO_SCHEMA") != "Clip.1":
                    continue

                media_ref = item.get("media_reference", {})
                if media_ref.get("OTIO_SCHEMA") != "ExternalReference.1":
                    continue

                asset_id = media_ref.get("asset_id")
                if not asset_id or asset_id not in asset_map:
                    continue

                if asset_id not in input_index_map:
                    input_index_map[asset_id] = len(inputs)
                    inputs.append(asset_map[asset_id])

                input_idx = input_index_map[asset_id]

                source_range = item.get("source_range", {})
                start_time = source_range.get("start_time", {})
                duration = source_range.get("duration", {})

                start_sec = start_time.get("value", 0) / start_time.get("rate", 24)
                dur_sec = duration.get("value", 0) / duration.get("rate", 24)

                if track_kind == "Video":
                    seg_label = f"v{len(video_segments)}"
                    filters.append(
                        f"[{input_idx}:v]trim=start={start_sec}:duration={dur_sec},"
                        f"setpts=PTS-STARTPTS[{seg_label}]"
                    )
                    video_segments.append(seg_label)

                    aseg_label = f"a{len(audio_segments)}"
                    filters.append(
                        f"[{input_idx}:a]atrim=start={start_sec}:duration={dur_sec},"
                        f"asetpts=PTS-STARTPTS[{aseg_label}]"
                    )
                    audio_segments.append(aseg_label)

                elif track_kind == "Audio":
                    seg_label = f"a{len(audio_segments)}"
                    filters.append(
                        f"[{input_idx}:a]atrim=start={start_sec}:duration={dur_sec},"
                        f"asetpts=PTS-STARTPTS[{seg_label}]"
                    )
                    audio_segments.append(seg_label)

        maps = []

        if video_segments:
            if len(video_segments) == 1:
                maps.append(f"[{video_segments[0]}]")
            else:
                concat_inputs = "".join(f"[{s}]" for s in video_segments)
                filters.append(
                    f"{concat_inputs}concat=n={len(video_segments)}:v=1:a=0[vout]"
                )
                maps.append("[vout]")

        if audio_segments:
            if len(audio_segments) == 1:
                maps.append(f"[{audio_segments[0]}]")
            else:
                concat_inputs = "".join(f"[{s}]" for s in audio_segments)
                filters.append(
                    f"{concat_inputs}concat=n={len(audio_segments)}:v=0:a=1[aout]"
                )
                maps.append("[aout]")

        filter_complex = ";".join(filters) if filters else ""

        if not filter_complex and inputs:
            maps = ["0:v", "0:a"]

        return inputs, filter_complex, maps

    def _build_encoding_options(self, preset: dict[str, Any]) -> list[str]:
        options = []
        video = preset.get("video", {})
        audio = preset.get("audio", {})
        use_gpu = preset.get("use_gpu", False)

        codec = video.get("codec", "h264")
        if use_gpu:
            if codec == "h264":
                options.extend(["-c:v", "h264_nvenc"])
            elif codec == "h265":
                options.extend(["-c:v", "hevc_nvenc"])
        else:
            if codec == "h264":
                options.extend(["-c:v", "libx264"])
            elif codec == "h265":
                options.extend(["-c:v", "libx265"])

        crf = video.get("crf", 23)
        if use_gpu:
            options.extend(["-cq", str(crf)])
        else:
            options.extend(["-crf", str(crf)])

        enc_preset = video.get("preset", "medium")
        if use_gpu:
            nvenc_map = {
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
            enc_preset = nvenc_map.get(enc_preset, "medium")
        options.extend(["-preset", enc_preset])

        pix_fmt = video.get("pixel_format", "yuv420p")
        options.extend(["-pix_fmt", pix_fmt])

        audio_codec = audio.get("codec", "aac")
        if audio_codec == "aac":
            options.extend(["-c:a", "aac"])
        elif audio_codec == "mp3":
            options.extend(["-c:a", "libmp3lame"])

        audio_bitrate = audio.get("bitrate", "192k")
        options.extend(["-b:a", audio_bitrate])

        options.extend(["-movflags", "+faststart"])

        return options

    def _execute_ffmpeg(
        self,
        cmd: list[str],
        progress_callback: Callable[[int, str | None], None] | None = None,
    ) -> str:
        output_path = cmd[-1]

        cmd_with_progress = cmd[:-1] + ["-progress", "pipe:1", cmd[-1]]

        logger.info("Executing FFmpeg...")
        logger.debug(f"Command: {' '.join(cmd_with_progress)}")

        try:
            process = subprocess.Popen(
                cmd_with_progress,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
            )

            duration = None
            last_progress = 10

            for line in process.stdout:
                line = line.strip()

                if line.startswith("Duration:"):
                    match = re.search(r"Duration: (\d+):(\d+):(\d+)", line)
                    if match:
                        h, m, s = map(int, match.groups())
                        duration = h * 3600 + m * 60 + s

                if line.startswith("out_time_ms="):
                    try:
                        time_ms = int(line.split("=")[1])
                        time_sec = time_ms / 1000000

                        if duration and duration > 0:
                            pct = min(95, 10 + int((time_sec / duration) * 85))
                            if pct > last_progress and progress_callback:
                                progress_callback(pct, None)
                                last_progress = pct
                    except (ValueError, IndexError):
                        pass

            process.wait()

            if process.returncode != 0:
                stderr = process.stderr.read() if process.stderr else ""
                raise RenderError(
                    f"FFmpeg failed (code {process.returncode}): {stderr}"
                )

            if progress_callback:
                progress_callback(95, "Finalizing output")

            return output_path

        except subprocess.SubprocessError as e:
            raise RenderError(f"Failed to execute FFmpeg: {e}")

    def cleanup(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)
