import json
import os
import dotenv

from google.cloud import storage
from google.cloud.exceptions import Conflict, NotFound
from google.oauth2 import service_account


dotenv.load_dotenv()


def _get_storage_client() -> storage.Client:
    credentials = os.getenv("GCP_CREDENTIALS")
    credentials_info = json.loads(credentials)
    credentials = service_account.Credentials.from_service_account_info(credentials_info)
    return storage.Client(credentials=credentials, project=credentials_info.get("project_id"))

def _get_bucket(bucket_name: str) -> storage.Bucket:
    storage_client = _get_storage_client()
    return storage_client.bucket(bucket_name)

def init_bucket(bucket_name: str) -> bool:
    try:
        storage_client = _get_storage_client()
        bucket = storage_client.bucket(bucket_name)
        bucket.storage_class = 'STANDARD'
        
        new_bucket = storage_client.create_bucket(bucket)
        return True
    except Conflict:
        return True
    except Exception as e:
        print(f"Error creating bucket: {e}")
        return False

def upload_file(bucket_name: str, contents: str, destination_blob_name: str) -> bool:
    try:
        bucket = _get_bucket(bucket_name)
        blob = bucket.blob(destination_blob_name)
        blob.upload_from_string(contents)
        return True
    except Exception as e:
        print(f"Error uploading file: {e}")
        return False

def download_file(bucket_name: str, blob_name: str) -> str:
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