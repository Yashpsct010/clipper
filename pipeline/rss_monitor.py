import json
import xml.etree.ElementTree as ET
import requests
from typing import List, Dict, Any, Optional
from pathlib import Path
from config import PROCESSED_FILE

def get_channel_id_from_url_or_handle(url_or_id: str) -> Optional[str]:
    """Extracts or resolves a YouTube channel ID from a raw ID, custom URL, or handle."""
    url_or_id = url_or_id.strip()
    # If it's already a standard 24-character channel ID starting with UC
    if url_or_id.startswith("UC") and len(url_or_id) == 24:
        return url_or_id
        
    # If user provided a full channel URL with /channel/UC...
    if "/channel/" in url_or_id:
        parts = url_or_id.split("/channel/")
        chan_id = parts[1].split("/")[0].split("?")[0]
        if chan_id.startswith("UC"):
            return chan_id
            
    # Try fetching page to find channelId tag (for handles like @creator)
    try:
        clean_url = url_or_id if url_or_id.startswith("http") else f"https://www.youtube.com/{url_or_id}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get(clean_url, headers=headers, timeout=10)
        if resp.status_code == 200:
            import re
            match = re.search(r'channel_id=([a-zA-Z0-9_-]{24})', resp.text)
            if match:
                return match.group(1)
            match_canonical = re.search(r'<meta itemprop="channelId" content="([a-zA-Z0-9_-]{24})"', resp.text)
            if match_canonical:
                return match_canonical.group(1)
    except Exception as e:
        print(f"[RSS Monitor] Could not resolve channel ID: {e}")
        
    return None

def fetch_latest_channel_videos(channel_id: str, limit: int = 5) -> List[Dict[str, str]]:
    """Fetches the latest videos for a YouTube channel using its public RSS feed."""
    rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    videos = []
    
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(rss_url, headers=headers, timeout=10)
        if resp.status_code != 200:
            print(f"[RSS Monitor] Failed to fetch RSS. Status code: {resp.status_code}")
            return []
            
        root = ET.fromstring(resp.content)
        # XML namespaces used by YouTube RSS
        ns = {
            'atom': 'http://www.w3.org/2005/Atom',
            'yt': 'http://www.youtube.com/xml/schemas/2015'
        }
        
        entries = root.findall('atom:entry', ns)
        for entry in entries[:limit]:
            video_id_elem = entry.find('yt:videoId', ns)
            title_elem = entry.find('atom:title', ns)
            link_elem = entry.find('atom:link', ns)
            published_elem = entry.find('atom:published', ns)
            
            if video_id_elem is not None and title_elem is not None:
                v_id = video_id_elem.text or ""
                v_title = title_elem.text or "Untitled"
                v_link = link_elem.attrib.get('href', f"https://www.youtube.com/watch?v={v_id}") if link_elem is not None else f"https://www.youtube.com/watch?v={v_id}"
                v_pub = published_elem.text if published_elem is not None else ""
                
                videos.append({
                    "video_id": v_id,
                    "title": v_title,
                    "link": v_link,
                    "published": v_pub
                })
    except Exception as e:
        print(f"[RSS Monitor] Error parsing RSS: {e}")
        
    return videos

def load_processed_records() -> Dict[str, Any]:
    """Loads records of previously processed videos."""
    if PROCESSED_FILE.exists():
        try:
            with open(PROCESSED_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[RSS Monitor] Error reading processed records: {e}")
    return {"processed": {}, "history": []}

def save_processed_records(data: Dict[str, Any]):
    """Saves records to processed_videos.json."""
    try:
        with open(PROCESSED_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[RSS Monitor] Error saving processed records: {e}")

def mark_video_status(video_id: str, title: str, status: str, clips_count: int = 0, details: str = ""):
    """Updates status for a given video in the record."""
    records = load_processed_records()
    from datetime import datetime
    timestamp = datetime.now().isoformat()
    
    records["processed"][video_id] = {
        "title": title,
        "status": status,
        "clips_count": clips_count,
        "updated_at": timestamp,
        "details": details
    }
    
    # Also log to linear history list
    records["history"].insert(0, {
        "timestamp": timestamp,
        "video_id": video_id,
        "title": title,
        "status": status,
        "clips_count": clips_count,
        "details": details
    })
    # Keep history bounded to 100 items
    records["history"] = records["history"][:100]
    
    save_processed_records(records)

def get_unprocessed_videos(channel_id: str) -> List[Dict[str, str]]:
    """Returns videos that have not yet been successfully processed."""
    latest = fetch_latest_channel_videos(channel_id, limit=5)
    records = load_processed_records()["processed"]
    
    unprocessed = []
    for v in latest:
        vid = v["video_id"]
        # Skip if already marked as completed or in_progress
        if vid in records and records[vid].get("status") in ["completed", "in_progress"]:
            continue
        unprocessed.append(v)
        
    return unprocessed
