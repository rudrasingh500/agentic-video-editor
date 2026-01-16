#!/usr/bin/env python3


import argparse
import json
import logging
import os
import sys

from google.cloud import storage

from ffmpeg_renderer import FFmpegRenderer, RenderError


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("render-job")


def parse_args():
    parser = argparse.ArgumentParser(description="Video render job")
    parser.add_argument(
        "--manifest",
        required=True,
        help="GCS path to render manifest (gs://bucket/path/manifest.json)",
    )
    parser.add_argument(
        "--job-id",
        required=True,
        help="Render job ID for status reporting",
    )
    return parser.parse_args()


def download_manifest(gcs_path: str) -> dict:
    if not gcs_path.startswith("gs://"):
        raise ValueError(f"Invalid GCS path: {gcs_path}")

    parts = gcs_path[5:].split("/", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid GCS path: {gcs_path}")

    bucket_name, blob_path = parts

    logger.info(f"Downloading manifest from {gcs_path}")

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_path)

    manifest_json = blob.download_as_text()
    return json.loads(manifest_json)


def report_status(
    callback_url: str | None,
    job_id: str,
    status: str,
    progress: int = 0,
    error_message: str | None = None,
):
    if not callback_url:
        logger.info(f"Status: {status}, Progress: {progress}%")
        return

    import requests

    try:
        payload = {
            "job_id": job_id,
            "status": status,
            "progress": progress,
            "error_message": error_message,
        }
        response = requests.post(callback_url, json=payload, timeout=10)
        response.raise_for_status()
    except Exception as e:
        logger.warning(f"Failed to report status: {e}")


def main():
    args = parse_args()

    job_id = args.job_id
    callback_url = os.environ.get("CALLBACK_URL")

    try:
        report_status(callback_url, job_id, "processing", 5)
        manifest = download_manifest(args.manifest)

        logger.info(f"Processing render job {job_id}")
        logger.info(f"Timeline version: {manifest.get('timeline_version')}")

        renderer = FFmpegRenderer(manifest)

        def progress_callback(progress: int, message: str | None = None):
            scaled = 5 + int(progress * 0.9)
            report_status(callback_url, job_id, "processing", scaled)
            if message:
                logger.info(message)

        report_status(callback_url, job_id, "processing", 10)
        output_path = renderer.render(progress_callback=progress_callback)

        logger.info(f"Render complete: {output_path}")

        report_status(callback_url, job_id, "completed", 100)

        logger.info("Job completed successfully")
        sys.exit(0)

    except RenderError as e:
        logger.error(f"Render failed: {e}")
        report_status(callback_url, job_id, "failed", error_message=str(e))
        sys.exit(1)

    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        report_status(callback_url, job_id, "failed", error_message=str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
