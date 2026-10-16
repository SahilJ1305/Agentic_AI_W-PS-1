import os
import uuid
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# Initialize Supabase Client
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
BUCKET_NAME = "pickup-images"  # Make sure you create this bucket in Supabase Dashboard

# Check if credentials exist
if not SUPABASE_URL or not SUPABASE_KEY:
    print("Warning: Supabase credentials missing in .env")
    supabase = None
else:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def upload_file_to_supabase(file_bytes, file_name: str, content_type: str) -> str:
    """
    Uploads file to Supabase and returns the Public URL.
    """
    if not supabase:
        return None

    try:
        # Generate a unique path: pickups/uuid-filename.jpg
        unique_filename = f"pickups/{uuid.uuid4()}-{file_name}"
        
        # Upload
        supabase.storage.from_(BUCKET_NAME).upload(
            path=unique_filename,
            file=file_bytes,
            file_options={"content-type": content_type}
        )
        
        # Get Public URL
        public_url = supabase.storage.from_(BUCKET_NAME).get_public_url(unique_filename)
        return public_url

    except Exception as e:
        print(f"Supabase Upload Error: {str(e)}")
        return None