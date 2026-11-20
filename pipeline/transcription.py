import re
from typing import List, Dict, Any, Optional, Tuple
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound

def extract_video_id(url_or_id: str) -> str:
    """Extracts YouTube video ID from various URL formats or returns the input if already an ID."""
    url_or_id = url_or_id.strip()
    if len(url_or_id) == 11 and re.match(r'^[a-zA-Z0-9_-]{11}$', url_or_id):
        return url_or_id
        
    patterns = [
        r'(?:v=|\/v\/|youtu\.be\/|\/embed\/|\/live\/|\/shorts\/)([a-zA-Z0-9_-]{11})',
        r'watch\?.*v=([a-zA-Z0-9_-]{11})'
    ]
    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)
            
    return url_or_id

def seconds_to_timestamp(seconds: float) -> str:
    """Converts seconds into HH:MM:SS format."""
    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"

def timestamp_to_seconds(ts: str) -> float:
    """Converts MM:SS or HH:MM:SS or float string into seconds."""
    ts = str(ts).strip()
    parts = ts.split(":")
    try:
        if len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        elif len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 1:
            return float(parts[0])
    except ValueError:
        pass
    return 0.0

def fetch_youtube_transcript(video_id: str) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    """
    Fetches transcript for a YouTube video using youtube-transcript-api.
    Returns (raw_transcript_list, formatted_string_for_llm) or (None, error_message).
    """
    video_id = extract_video_id(video_id)
    preferred_languages = ['en', 'en-US', 'en-GB', 'en-CA', 'en-AU']
    
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        
        # Try finding a manual or auto-generated English transcript
        transcript_obj = None
        try:
            transcript_obj = transcript_list.find_manually_created_transcript(preferred_languages)
        except Exception:
            try:
                transcript_obj = transcript_list.find_generated_transcript(preferred_languages)
            except Exception:
                # If no direct English transcript, pick the first available and translate to English
                for t in transcript_list:
                    if t.is_translatable:
                        transcript_obj = t.translate('en')
                        break
                        
        if not transcript_obj:
            return None, "No suitable transcript found (transcripts may not be generated yet)."
            
        raw_items = transcript_obj.fetch()
        
        # Format text with timestamps for LLM consumption
        # To avoid blowing up tokens for 4-hour streams, group phrases into ~15-second blocks
        formatted_lines = []
        current_block_start = 0.0
        current_block_text = []
        
        for item in raw_items:
            start = item.get('start', 0.0)
            text = item.get('text', '').replace('\n', ' ').strip()
            if not text:
                continue
                
            if not current_block_text:
                current_block_start = start
                
            current_block_text.append(text)
            
            # Flush block every 15 seconds or when block text has ~30 words
            if (start - current_block_start >= 15.0) or len(' '.join(current_block_text).split()) >= 30:
                ts_str = seconds_to_timestamp(current_block_start)
                formatted_lines.append(f"[{ts_str}] {' '.join(current_block_text)}")
                current_block_text = []
                
        if current_block_text:
            ts_str = seconds_to_timestamp(current_block_start)
            formatted_lines.append(f"[{ts_str}] {' '.join(current_block_text)}")
            
        formatted_transcript = "\n".join(formatted_lines)
        return raw_items, formatted_transcript

    except TranscriptsDisabled:
        return None, "Transcripts are disabled on this video."
    except NoTranscriptFound:
        return None, "No transcript was found for this video."
    except Exception as e:
        return None, f"Error retrieving transcript: {str(e)}"

def get_transcript_slice(raw_items: List[Dict[str, Any]], start_sec: float, end_sec: float) -> List[Dict[str, Any]]:
    """Returns the subset of transcript items between start_sec and end_sec."""
    slice_items = []
    for item in raw_items:
        item_start = item.get('start', 0.0)
        item_dur = item.get('duration', 0.0)
        item_end = item_start + item_dur
        
        # Check overlap
        if item_end >= start_sec and item_start <= end_sec:
            slice_items.append({
                "start": max(0.0, item_start - start_sec),  # Relativize to snippet start
                "duration": item_dur,
                "text": item.get('text', '').replace('\n', ' ').strip()
            })
    return slice_items
