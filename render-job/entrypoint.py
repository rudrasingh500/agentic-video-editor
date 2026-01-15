#!/usr/bin/env python3
"""
Render job entrypoint.

This script is the entry point for the Cloud Run render job container.
It:
1. Parses command-line arguments
2. Downloads the render manifest from GCS
3. Executes the FFmpeg render
4. Uploads the result to GCS
5. Reports status back to the backend
"""

import argparse
import json
import logging
import os
import sys

from google.cloud import storage

from ffmpeg_renderer import FFmpegRenderer, RenderError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("render-job")


def parse_args():
    """Parse command line arguments."""
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
    """
    Download render manifest from GCS.

    Args:
        gcs_path: GCS URI (gs://bucket/path/to/manifest.json)

    Returns:
        Parsed manifest dict
    """
    # Parse GCS URI
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
    """
    Report status back to backend API.

    Args:
        callback_url: Backend webhook URL
        job_id: Render job ID
        status: Status string (processing, completed, failed)
        progress: Progress percentage (0-100)
        error_message: Error message if failed
    """
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
    """Main entry point."""
    args = parse_args()

    job_id = args.job_id
    callback_url = os.environ.get("CALLBACK_URL")

    try:
        # Download manifest
        report_status(callback_url, job_id, "processing", 5)
        manifest = download_manifest(args.manifest)

        logger.info(f"Processing render job {job_id}")
        logger.info(f"Timeline version: {manifest.get('timeline_version')}")

        # Create renderer
        renderer = FFmpegRenderer(manifest)

        # Define progress callback
        def progress_callback(progress: int, message: str | None = None):
            # Scale progress: 5-95% for actual rendering
            scaled = 5 + int(progress * 0.9)
            report_status(callback_url, job_id, "processing", scaled)
            if message:
                logger.info(message)

        # Execute render
        report_status(callback_url, job_id, "processing", 10)
        output_path = renderer.render(progress_callback=progress_callback)

        logger.info(f"Render complete: {output_path}")

        # Report completion
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
