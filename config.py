import os
import json
from pathlib import Path
from typing import Dict, Any

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CONFIG_FILE = DATA_DIR / "config.json"
PROCESSED_FILE = DATA_DIR / "processed_videos.json"
OUTPUT_DIR = DATA_DIR / "output_clips"
TEMP_DIR = DATA_DIR / "temp"

# Ensure runtime directories exist
for folder in [DATA_DIR, OUTPUT_DIR, TEMP_DIR]:
    folder.mkdir(parents=True, exist_ok=True)

DEFAULT_CONFIG: Dict[str, Any] = {
    # Gemini AI API Key (Free from Google AI Studio)
    "gemini_api_key": os.getenv("GEMINI_API_KEY", ""),
    
    # Target YouTube Channel ID to monitor (e.g. UC_x5XG1OV2P6uZZ5FSM9Ttw)
    "target_channel_id": os.getenv("TARGET_CHANNEL_ID", ""),
    
    # Check frequency in minutes
    "check_interval_minutes": int(os.getenv("CHECK_INTERVAL_MINUTES", "60")),
    
    # Autopilot status
    "autopilot_enabled": os.getenv("AUTOPILOT_ENABLED", "false").lower() == "true",
    
    # YouTube Upload Settings
    "auto_upload": os.getenv("AUTO_UPLOAD", "false").lower() == "true",
    "video_privacy": os.getenv("VIDEO_PRIVACY", "private"),  # 'private', 'unlisted', or 'public'
    
    # Video Editing Layout Settings
    # Options: 'split_screen' (Facecam top, gameplay bottom), 'blurred_background', 'center_crop'
    "layout_mode": os.getenv("LAYOUT_MODE", "split_screen"),
    
    # Facecam crop box (for 1920x1080 source): [x, y, width, height]
    # Default is top-right corner where streamers usually put facecam
    "facecam_crop": [1380, 40, 500, 380],
    
    # Gameplay crop box (for 1920x1080 source): [x, y, width, height]
    # Default takes wide center area of gameplay
    "gameplay_crop": [160, 0, 1600, 1080],
    
    # How many shorts to extract per long video/stream
    "max_clips_per_video": int(os.getenv("MAX_CLIPS_PER_VIDEO", "3")),
    
    # Subtitle Styling
    "burn_subtitles": True,
    "subtitle_font_size": 22,
    "subtitle_primary_color": "&H0000FFFF",  # Yellow in ASS hex (&HAABBGGRR)
    "subtitle_outline_color": "&H00000000",  # Black outline
}

def load_config() -> Dict[str, Any]:
    """Loads config merging default, environment variables, and saved JSON file."""
    config = DEFAULT_CONFIG.copy()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                config.update(saved)
        except Exception as e:
            print(f"[Config] Error loading config.json: {e}")
            
    # Environment variables always override if set
    for key in DEFAULT_CONFIG:
        env_val = os.getenv(key.upper())
        if env_val is not None:
            if isinstance(DEFAULT_CONFIG[key], bool):
                config[key] = env_val.lower() == "true"
            elif isinstance(DEFAULT_CONFIG[key], int):
                config[key] = int(env_val)
            else:
                config[key] = env_val
                
    return config

def save_config(new_config: Dict[str, Any]) -> bool:
    """Saves updated config to config.json."""
    try:
        current = load_config()
        current.update(new_config)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2)
        return True
    except Exception as e:
        print(f"[Config] Error saving config: {e}")
        return False
