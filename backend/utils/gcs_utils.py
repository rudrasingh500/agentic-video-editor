from __future__ import annotations

import io
import json
import os
from datetime import timedelta
from typing import Optional

import dotenv
from google.cloud import storage
from google.cloud.exceptions import Conflict, NotFound
from google.oauth2 import service_account


dotenv.load_dotenv()


def _get_storage_client() -> storage.Client:
    credentials_raw: str = os.getenv("GCP_CREDENTIALS", "")
    if not credentials_raw:
        return storage.Client()
    credentials_info = json.loads(credentials_raw)
    credentials = service_account.Credentials.from_service_account_info(
        credentials_info
    )
    return storage.Client(
        credentials=credentials, project=credentials_info.get("project_id")
    )


def _get_bucket(bucket_name: str) -> storage.Bucket:
    storage_client = _get_storage_client()
    return storage_client.bucket(bucket_name)


def init_bucket(bucket_name: str) -> bool:
    try:
        storage_client = _get_storage_client()
        bucket = storage_client.bucket(bucket_name)
        bucket.storage_class = "STANDARD"

        storage_client.create_bucket(bucket)
        return True
    except Conflict:
        return True
    except Exception as e:
        print(f"Error creating bucket: {e}")
        return False


def upload_file(bucket_name: str, contents: bytes, destination_blob_name: str) -> dict:
    try:
        bucket = _get_bucket(bucket_name)
        blob = bucket.blob(destination_blob_name)
        blob.upload_from_file(io.BytesIO(contents))
        blob.reload()

        return {
            "path": blob.name,
            "content_type": blob.content_type,
            "size": blob.size,
        }
    except Exception as e:
        print(f"Error uploading file: {e}")
        return {}


def download_file(bucket_name: str, blob_name: str) -> Optional[bytes]:
    try:
        bucket = _get_bucket(bucket_name)
        blob = bucket.blob(blob_name)
        return blob.download_as_bytes()
    except Exception as e:
        print(f"Error downloading file: {e}")
        return None


def delete_file(bucket_name: str, blob_name: str) -> bool:
    try:
        bucket = _get_bucket(bucket_name)
        blob = bucket.blob(blob_name)
        blob.delete()
        return True
    except NotFound:
        print(f"File {blob_name} not found in bucket {bucket_name}")
        return False
    except Exception as e:
        print(f"Error deleting file: {e}")
        return False


def parse_gcs_url(url: str) -> tuple[str, str] | None:
    if not url:
        return None
    if url.startswith("gs://"):
        parts = url[5:].split("/", 1)
        if len(parts) != 2:
            return None
        return parts[0], parts[1]
    return None


def generate_signed_url(
    bucket_name: str,
    blob_name: str,
    expiration: timedelta | None = None,
) -> str:
    if expiration is None:
        expiration = timedelta(hours=1)
    bucket = _get_bucket(bucket_name)
    blob = bucket.blob(blob_name)
    return blob.generate_signed_url(expiration=expiration, method="GET", version="v4")
