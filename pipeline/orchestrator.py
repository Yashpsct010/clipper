import os
import json
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

from config import load_config, OUTPUT_DIR, TEMP_DIR
from pipeline.rss_monitor import (
    get_unprocessed_videos,
    mark_video_status,
    load_processed_records
)
from pipeline.transcription import (
    extract_video_id,
    fetch_youtube_transcript,
    get_transcript_slice
)
from pipeline.highlight_ai import detect_highlights_gemini
from pipeline.video_editor import (
    download_video_snippet,
    create_ass_subtitles,
    render_vertical_short
)
from pipeline.youtube_uploader import (
    upload_short_to_youtube,
    is_youtube_authenticated
)

def process_youtube_video(
    video_url_or_id: str,
    custom_config: Optional[Dict[str, Any]] = None,
    log_callback: Optional[callable] = None
) -> Dict[str, Any]:
    """
    Complete pipeline run for a single YouTube video or stream:
    1. Fetches transcript
    2. Identifies highlights with Gemini AI
    3. Downloads only highlight sections
    4. Slices & styles subtitles
    5. Renders 2-panel or blurred 9:16 vertical short
    6. Optionally uploads to YouTube
    """
    config = load_config()
    if custom_config:
        config.update(custom_config)
        
    def log(msg: str):
        print(f"[Pipeline] {msg}")
        if log_callback:
            log_callback(msg)

    video_id = extract_video_id(video_url_or_id)
    log(f"Starting processing for Video ID: {video_id}")
    
    # 1. Fetch transcript
    log("Fetching transcript from YouTube...")
    raw_transcript, formatted_transcript = fetch_youtube_transcript(video_id)
    if not raw_transcript:
        err_msg = f"Failed to get transcript: {formatted_transcript}"
        log(f"ERROR: {err_msg}")
        mark_video_status(video_id, f"Video {video_id}", "failed", 0, err_msg)
        return {"success": False, "error": err_msg, "clips": []}
        
    log(f"Transcript fetched successfully ({len(raw_transcript)} subtitle cues).")
    
    # 2. Highlight Detection with Gemini
    gemini_key = config.get("gemini_api_key", "")
    max_clips = config.get("max_clips_per_video", 3)
    log(f"Analyzing transcript with Gemini AI for top {max_clips} viral moments...")
    
    clips, err = detect_highlights_gemini(
        transcript_text=formatted_transcript,
        video_title=f"YouTube Stream {video_id}",
        api_key=gemini_key,
        max_clips=max_clips
    )
    if err or not clips:
        err_msg = f"AI Highlight detection failed: {err}"
        log(f"ERROR: {err_msg}")
        mark_video_status(video_id, f"Video {video_id}", "failed", 0, err_msg)
        return {"success": False, "error": err_msg, "clips": []}
        
    log(f"Gemini identified {len(clips)} viral clips!")
    
    # 3. Process each clip
    generated_clips = []
    video_full_url = f"https://www.youtube.com/watch?v={video_id}"
    
    for idx, clip in enumerate(clips, start=1):
        start_sec = clip["start_sec"]
        end_sec = clip["end_sec"]
        hook_headline = clip.get("hook_headline", "")
        short_title = clip.get("short_title", f"Clip {idx} from {video_id}")
        short_desc = clip.get("description", "")
        tags = clip.get("tags", [])
        
        clip_uid = str(uuid.uuid4())[:8]
        raw_snippet_file = f"snippet_{video_id}_{idx}_{clip_uid}.mp4"
        ass_sub_file = TEMP_DIR / f"sub_{video_id}_{idx}_{clip_uid}.ass"
        final_short_file = f"short_{video_id}_{idx}_{clip_uid}.mp4"
        
        log(f"--- Processing Clip #{idx}/{len(clips)}: [{clip.get('start_time')} -> {clip.get('end_time')}] (Score: {clip.get('viral_score')}) ---")
        log(f"Downloading {clip.get('duration_sec', 45):.1f}s segment from YouTube via yt-dlp...")
        
        downloaded_raw, dl_err = download_video_snippet(
            video_url=video_full_url,
            start_sec=start_sec,
            end_sec=end_sec,
            output_filename=raw_snippet_file
        )
        if dl_err or not downloaded_raw:
            log(f"Warning: Failed to download clip #{idx}: {dl_err}")
            continue
            
        # Generate Subtitles
        log("Creating animated karaoke subtitles...")
        transcript_slice = get_transcript_slice(raw_transcript, start_sec, end_sec)
        create_ass_subtitles(
            transcript_slice=transcript_slice,
            output_ass_path=ass_sub_file,
            font_size=config.get("subtitle_font_size", 22),
            primary_color=config.get("subtitle_primary_color", "&H0000FFFF")
        )
        
        # Render Vertical Short
        layout_mode = config.get("layout_mode", "split_screen")
        log(f"Rendering vertical 9:16 Short with layout mode: '{layout_mode}'...")
        
        rendered_path, render_err = render_vertical_short(
            input_video=downloaded_raw,
            output_filename=final_short_file,
            layout_mode=layout_mode,
            facecam_crop=config.get("facecam_crop"),
            gameplay_crop=config.get("gameplay_crop"),
            hook_headline=hook_headline,
            ass_subtitle_path=str(ass_sub_file) if config.get("burn_subtitles", True) else None
        )
        
        # Clean up temporary raw snippet
        try:
            if Path(downloaded_raw).exists():
                Path(downloaded_raw).unlink()
            if ass_sub_file.exists():
                ass_sub_file.unlink()
        except Exception:
            pass
            
        if render_err or not rendered_path:
            log(f"Render failed for clip #{idx}: {render_err}")
            continue
            
        log(f"SUCCESS! Rendered short: {final_short_file}")
        
        clip_info = {
            "file_path": rendered_path,
            "filename": final_short_file,
            "title": short_title,
            "description": short_desc,
            "tags": tags,
            "hook": hook_headline,
            "viral_score": clip.get("viral_score"),
            "uploaded": False,
            "youtube_id": None
        }
        
        # 4. Optional Auto-Upload to YouTube
        if config.get("auto_upload", False):
            if is_youtube_authenticated():
                log("Auto-upload enabled. Uploading Short to YouTube...")
                yt_id, up_err = upload_short_to_youtube(
                    video_path=rendered_path,
                    title=short_title,
                    description=short_desc,
                    tags=tags,
                    privacy_status=config.get("video_privacy", "private")
                )
                if yt_id:
                    log(f"Uploaded to YouTube! Video ID: {yt_id} (Privacy: {config.get('video_privacy')})")
                    clip_info["uploaded"] = True
                    clip_info["youtube_id"] = yt_id
                else:
                    log(f"Upload failed: {up_err}")
            else:
                log("Auto-upload is enabled, but YouTube is not authenticated yet.")
                
        generated_clips.append(clip_info)
        
    mark_video_status(
        video_id=video_id,
        title=f"YouTube Video {video_id}",
        status="completed" if generated_clips else "failed",
        clips_count=len(generated_clips),
        details=f"Generated {len(generated_clips)} shorts."
    )
    
    return {
        "success": len(generated_clips) > 0,
        "clips": generated_clips,
        "error": "" if generated_clips else "No clips could be successfully rendered."
    }

def run_autopilot_cycle(log_callback: Optional[callable] = None) -> Dict[str, Any]:
    """Runs a single check of the channel RSS feed and processes any newly published stream."""
    config = load_config()
    
    def log(msg: str):
        print(f"[Autopilot] {msg}")
        if log_callback:
            log_callback(msg)
            
    if not config.get("autopilot_enabled", False):
        log("Autopilot is disabled in configuration. Skipping check.")
        return {"status": "disabled", "processed": 0}
        
    channel_id = config.get("target_channel_id", "").strip()
    if not channel_id:
        log("No target channel ID specified. Set it in Settings.")
        return {"status": "no_channel", "processed": 0}
        
    log(f"Checking YouTube RSS for channel: {channel_id}...")
    unprocessed = get_unprocessed_videos(channel_id)
    
    if not unprocessed:
        log("No new unprocessed videos found. All up to date.")
        return {"status": "up_to_date", "processed": 0}
        
    log(f"Found {len(unprocessed)} new video(s) to process! Starting with the latest...")
    # Process the most recent video
    latest_video = unprocessed[0]
    vid = latest_video["video_id"]
    title = latest_video["title"]
    
    log(f"Processing new stream: '{title}' ({vid})")
    result = process_youtube_video(vid, config, log_callback=log)
    return {"status": "completed", "processed": 1, "result": result}
