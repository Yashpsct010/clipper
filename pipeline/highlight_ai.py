import json
import re
from typing import List, Dict, Any, Optional, Tuple
import google.generativeai as genai
from pipeline.transcription import timestamp_to_seconds

HIGHLIGHT_PROMPT = """You are an elite short-form video editor and viral content strategist specializing in YouTube Shorts, TikTok, and Instagram Reels.
You will receive a timestamped transcript from a long YouTube video or livestream titled "{video_title}".

YOUR OBJECTIVE:
Find the TOP {max_clips} most viral, engaging, and entertaining segments (each between 30 and 60 seconds long) that will perform exceptionally well as a YouTube Short.

CRITERIA FOR VIRAL CLIPS:
1. Strong Opening Hook: Begins immediately with action, a bold statement, an intense question, or a high-energy reaction within the first 3 seconds.
2. Complete Narrative / Punchline: The clip tells a mini-story or delivers a funny, shocking, or satisfying conclusion by the end.
3. High Emotion / Energy: Laughter, shock, clutch gameplay moments, deep insight, heated debate, or unexpected twists.
4. Retention-Friendly: Avoid dead air, long pauses, technical setup discussions, or "I'll be right back" segments.

Output strictly valid JSON conforming to this structure:
{{
  "clips": [
    {{
      "start_time": "HH:MM:SS or MM:SS",
      "end_time": "HH:MM:SS or MM:SS",
      "viral_score": 95,
      "reason": "Why this moment is viral",
      "hook_headline": "SHORT 3-5 WORD UPPERCASE HOOK BANNER",
      "short_title": "Engaging Viral Title #shorts #gaming",
      "description": "Engaging description summarizing the clip.\\n\\n#shorts #highlight #streamer",
      "tags": ["shorts", "streamer", "highlight", "funny"]
    }}
  ]
}}

Here is the transcript:
\"\"\"
{transcript_text}
\"\"\"
"""

def detect_highlights_gemini(
    transcript_text: str,
    video_title: str,
    api_key: str,
    max_clips: int = 3
) -> Tuple[List[Dict[str, Any]], str]:
    """
    Calls Google Gemini API to analyze transcript and extract viral clip timestamps.
    Returns (clips_list, error_message).
    """
    if not api_key:
        return [], "Google Gemini API key is missing. Please set it in Settings or Space Secrets."
        
    try:
        genai.configure(api_key=api_key)
        # Prefer gemini-2.0-flash, fallback to gemini-1.5-flash
        model_name = "gemini-2.0-flash"
        try:
            model = genai.GenerativeModel(model_name)
        except Exception:
            model_name = "gemini-1.5-flash"
            model = genai.GenerativeModel(model_name)
            
        prompt = HIGHLIGHT_PROMPT.format(
            video_title=video_title,
            max_clips=max_clips,
            transcript_text=transcript_text[:50000] # Fit comfortably in context window
        )
        
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.4,
                response_mime_type="application/json"
            )
        )
        
        raw_text = response.text.strip()
        
        # Clean json markdown tags if present
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
        raw_text = raw_text.strip()
        
        data = json.loads(raw_text)
        clips = data.get("clips", [])
        
        # Validate and normalize clips
        valid_clips = []
        for c in clips:
            start_ts = c.get("start_time", "00:00")
            end_ts = c.get("end_time", "00:45")
            start_sec = timestamp_to_seconds(start_ts)
            end_sec = timestamp_to_seconds(end_ts)
            
            # Enforce 20s to 75s duration
            duration = end_sec - start_sec
            if duration < 15.0 or duration > 90.0:
                if duration <= 0:
                    end_sec = start_sec + 45.0
                    duration = 45.0
                elif duration > 90.0:
                    end_sec = start_sec + 60.0
                    duration = 60.0
                    
            c["start_sec"] = start_sec
            c["end_sec"] = end_sec
            c["duration_sec"] = duration
            valid_clips.append(c)
            
        valid_clips.sort(key=lambda x: x.get("viral_score", 0), reverse=True)
        return valid_clips[:max_clips], ""
        
    except Exception as e:
        return [], f"Gemini API Error: {str(e)}"
