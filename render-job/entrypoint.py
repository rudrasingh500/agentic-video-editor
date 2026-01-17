#!/usr/bin/env python3


import argparse
import json
import logging
import os
import sys
from pathlib import Path


from google.cloud import storage
from google.oauth2 import service_account


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
        help="GCS path or local path to render manifest",
    )
    parser.add_argument(
        "--job-id",
        required=True,
        help="Render job ID for status reporting",
    )
    return parser.parse_args()



def _get_storage_client() -> storage.Client:
    credentials_json = os.environ.get("GCP_CREDENTIALS")
    if not credentials_json:
        return storage.Client()

    try:
        credentials_info = json.loads(credentials_json)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid GCP_CREDENTIALS JSON") from exc

    credentials = service_account.Credentials.from_service_account_info(
        credentials_info
    )
    return storage.Client(
        credentials=credentials, project=credentials_info.get("project_id")
    )


def download_manifest(manifest_path: str) -> dict:
    if manifest_path.startswith("gs://"):
        parts = manifest_path[5:].split("/", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid GCS path: {manifest_path}")

        bucket_name, blob_path = parts

        logger.info(f"Downloading manifest from {manifest_path}")

        client = _get_storage_client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_path)

        manifest_json = blob.download_as_text()
        return json.loads(manifest_json)

    path = Path(manifest_path)
    if not path.exists():
        raise ValueError(f"Manifest file not found: {manifest_path}")

    logger.info(f"Loading manifest from {manifest_path}")
    return json.loads(path.read_text(encoding="utf-8"))



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
