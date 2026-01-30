import os
from google.cloud import storage
from google.oauth2 import service_account
import json
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv('.env')

def init_buckets():
    # Get configuration from env
    credentials_json = os.getenv('GCP_CREDENTIALS')
    
    if not credentials_json:
        print("Error: GCP_CREDENTIALS not found in .env")
        return

    try:
        credentials_info = json.loads(credentials_json)
        credentials = service_account.Credentials.from_service_account_info(credentials_info)
        storage_client = storage.Client(credentials=credentials, project=credentials_info.get('project_id'))
        
        # Define needed buckets (using defaults from backend code if not set in env)
        asset_bucket_name = os.getenv("GCS_BUCKET", "video-editor")
        render_bucket_name = os.getenv("GCS_RENDER_BUCKET", "video-editor-renders")
        
        buckets_to_create = [asset_bucket_name, render_bucket_name]
        
        print(f"Initializing buckets for project: {credentials_info.get('project_id')}")
        
        for bucket_name in buckets_to_create:
            try:
                bucket = storage_client.bucket(bucket_name)
                if not bucket.exists():
                    print(f"Creating bucket: {bucket_name}")
                    # Configure CORS for the bucket to allow browser uploads
                    cors_configuration = [
                        {
                            "origin": ["http://localhost:5173", "http://localhost:3000"],
                            "method": ["GET", "PUT", "POST", "DELETE", "OPTIONS"],
                            "responseHeader": ["Content-Type", "x-goog-resumable"],
                            "maxAgeSeconds": 3600
                        }
                    ]
                    
                    bucket.create(location="US")
                    bucket.cors = cors_configuration
                    bucket.patch()
                    print(f"✅ Bucket {bucket_name} created with CORS config")
                else:
                    print(f"ℹ️  Bucket {bucket_name} already exists")
                    
                    # Update CORS even if bucket exists, to ensure dev works
                    print(f"Updating CORS for {bucket_name}...")
                    cors_configuration = [
                        {
                            "origin": ["http://localhost:5173", "http://localhost:3000"],
                            "method": ["GET", "PUT", "POST", "DELETE", "OPTIONS"],
                            "responseHeader": ["Content-Type", "x-goog-resumable"],
                            "maxAgeSeconds": 3600
                        }
                    ]
                    bucket.cors = cors_configuration
                    bucket.patch()
                    print(f"✅ CORS updated for {bucket_name}")

            except Exception as e:
                print(f"❌ Error handling bucket {bucket_name}: {str(e)}")
                
    except json.JSONDecodeError as e:
        print(f"Error parsing GCP_CREDENTIALS: {str(e)}")
    except Exception as e:
        print(f"An unexpected error occurred: {str(e)}")

if __name__ == "__main__":
    init_buckets()
