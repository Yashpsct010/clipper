import os
import json
from pathlib import Path
from typing import Tuple, Optional, Dict, Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

from config import DATA_DIR

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_FILE = DATA_DIR / "token.json"
CLIENT_SECRETS_FILE = DATA_DIR / "client_secrets.json"

def get_youtube_service():
    """Builds and returns an authenticated YouTube API service, refreshing tokens if needed."""
    creds = None
    
    if TOKEN_FILE.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        except Exception as e:
            print(f"[YouTube Uploader] Error reading token file: {e}")

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                with open(TOKEN_FILE, "w", encoding="utf-8") as token_out:
                    token_out.write(creds.to_json())
            except Exception as e:
                print(f"[YouTube Uploader] Failed to refresh token: {e}")
                return None
        else:
            return None

    return build("youtube", "v3", credentials=creds)

def is_youtube_authenticated() -> bool:
    """Checks whether valid YouTube OAuth credentials exist."""
    service = get_youtube_service()
    return service is not None

def save_client_secrets_content(json_content: str) -> bool:
    """Saves user-provided client_secrets.json content."""
    try:
        # Validate that it is valid JSON
        data = json.loads(json_content)
        with open(CLIENT_SECRETS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        print(f"[YouTube Uploader] Invalid client secrets: {e}")
        return False

def save_token_content(json_content: str) -> bool:
    """Saves user-provided token.json content directly."""
    try:
        data = json.loads(json_content)
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        print(f"[YouTube Uploader] Invalid token: {e}")
        return False

def upload_short_to_youtube(
    video_path: str,
    title: str,
    description: str,
    tags: Optional[list] = None,
    privacy_status: str = "private"
) -> Tuple[Optional[str], str]:
    """
    Uploads a short video file to YouTube using YouTube Data API v3.
    Returns (youtube_video_id, error_message).
    """
    service = get_youtube_service()
    if not service:
        return None, "YouTube is not authenticated. Please upload token.json or client_secrets.json in Settings."
        
    path_obj = Path(video_path)
    if not path_obj.exists():
        return None, f"Video file not found: {video_path}"
        
    # Ensure #shorts is present in title and description
    clean_title = title if "#shorts" in title.lower() else f"{title} #shorts"
    clean_title = clean_title[:100]  # YouTube title limit
    
    clean_desc = description if "#shorts" in description.lower() else f"{description}\n\n#shorts"
    clean_tags = tags or ["shorts", "highlight", "viral"]
    
    body = {
        "snippet": {
            "title": clean_title,
            "description": clean_desc,
            "tags": clean_tags,
            "categoryId": "20"  # 20 = Gaming, 22 = People & Blogs
        },
        "status": {
            "privacyStatus": privacy_status.lower(),
            "selfDeclaredMadeForKids": False
        }
    }
    
    try:
        media = MediaFileUpload(
            video_path,
            chunksize=1024 * 1024 * 4,  # 4MB chunks
            resumable=True,
            mimetype="video/mp4"
        )
        
        request = service.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media
        )
        
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                print(f"[YouTube Uploader] Uploaded {int(status.progress() * 100)}%")
                
        uploaded_id = response.get("id")
        return uploaded_id, ""
        
    except HttpError as e:
        return None, f"YouTube API HttpError {e.resp.status}: {e.content.decode('utf-8')}"
    except Exception as e:
        return None, f"YouTube upload error: {str(e)}"
