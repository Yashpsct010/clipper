import os
import subprocess
import shutil
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from config import TEMP_DIR, OUTPUT_DIR
from pipeline.transcription import seconds_to_timestamp

def format_ass_time(seconds: float) -> str:
    """Formats seconds into ASS timestamp format: H:MM:SS.cs"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centis = int(round((seconds - int(seconds)) * 100))
    if centis >= 100:
        centis = 99
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"

def download_video_snippet(
    video_url: str,
    start_sec: float,
    end_sec: float,
    output_filename: str
) -> Tuple[Optional[str], str]:
    """
    Downloads only the specified start to end range of a YouTube video using yt-dlp.
    Returns (downloaded_file_path, error_message).
    """
    start_ts = seconds_to_timestamp(start_sec)
    end_ts = seconds_to_timestamp(end_sec)
    output_path = TEMP_DIR / output_filename
    
    if output_path.exists():
        output_path.unlink()
        
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "-f", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]/best",
        "--download-sections", f"*{start_ts}-{end_ts}",
        "--force-keyframes-at-cuts",
        "-o", str(output_path),
        video_url
    ]
    
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=180
        )
        if proc.returncode != 0:
            return None, f"yt-dlp download failed: {proc.stderr[:400]}"
            
        if not output_path.exists() or output_path.stat().st_size == 0:
            return None, "yt-dlp completed but output file was not found or is empty."
            
        return str(output_path), ""
    except subprocess.TimeoutExpired:
        return None, "Download timed out after 3 minutes."
    except Exception as e:
        return None, f"Error running yt-dlp: {str(e)}"

def create_ass_subtitles(
    transcript_slice: List[Dict[str, Any]],
    output_ass_path: Path,
    font_size: int = 22,
    primary_color: str = "&H0000FFFF",  # Yellow
    outline_color: str = "&H00000000"   # Black
) -> bool:
    """
    Generates a stylized ASS subtitle file with punchy, mobile-optimized word phrasing.
    """
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hormozi,Liberation Sans,{font_size * 2},{primary_color},&H000000FF,{outline_color},&H80000000,-1,0,0,0,100,100,1,0,1,6,2,2,40,40,240,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    
    # Process transcript items into short, 3 to 4 word rhythmic bursts
    for item in transcript_slice:
        start = item.get("start", 0.0)
        dur = item.get("duration", 2.0)
        text = item.get("text", "").strip()
        if not text:
            continue
            
        words = text.split()
        if not words:
            continue
            
        chunk_size = 4
        chunks = [words[i:i + chunk_size] for i in range(0, len(words), chunk_size)]
        chunk_dur = dur / max(1, len(chunks))
        
        for idx, chunk in enumerate(chunks):
            c_start = start + (idx * chunk_dur)
            c_end = c_start + chunk_dur
            c_text = " ".join(chunk).upper()
            
            # Escape braces for ASS
            c_text = c_text.replace("{", "(").replace("}", ")")
            
            start_str = format_ass_time(c_start)
            end_str = format_ass_time(c_end)
            events.append(f"Dialogue: 0,{start_str},{end_str},Hormozi,,0,0,0,,{c_text}")
            
    try:
        with open(output_ass_path, "w", encoding="utf-8") as f:
            f.write(header + "\n".join(events) + "\n")
        return True
    except Exception as e:
        print(f"[Video Editor] Error writing ASS file: {e}")
        return False

def render_vertical_short(
    input_video: str,
    output_filename: str,
    layout_mode: str = "split_screen",
    facecam_crop: Optional[List[int]] = None,
    gameplay_crop: Optional[List[int]] = None,
    hook_headline: str = "",
    ass_subtitle_path: Optional[str] = None
) -> Tuple[Optional[str], str]:
    """
    Renders input horizontal video into 1080x1920 vertical video with subtitles and split-layout using FFmpeg.
    """
    out_path = OUTPUT_DIR / output_filename
    if out_path.exists():
        out_path.unlink()
        
    fc = facecam_crop or [1380, 40, 500, 380]
    gp = gameplay_crop or [160, 0, 1600, 1080]
    
    # Clean hook headline text
    clean_hook = hook_headline.replace("'", "").replace(":", "-").replace('"', "").strip().upper()
    
    filters = []
    
    # 1. Base visual transformation
    if layout_mode == "split_screen":
        # Top 40% (1080x768) is facecam, Bottom 60% (1080x1152) is gameplay
        # Force aspect ratios and stack
        filter_str = (
            f"[0:v]crop={fc[2]}:{fc[3]}:{fc[0]}:{fc[1]},scale=1080:768,setsar=1[top]; "
            f"[0:v]crop={gp[2]}:{gp[3]}:{gp[0]}:{gp[1]},scale=1080:1152,setsar=1[bottom]; "
            f"[top][bottom]vstack=inputs=2[vbase]"
        )
        current_v = "[vbase]"
    elif layout_mode == "blurred_background":
        # Blurred background (1080x1920) + centered 16:9 foreground
        filter_str = (
            "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:5[bg]; "
            "[0:v]scale=1080:-1[fg]; "
            "[bg][fg]overlay=(W-w)/2:(H-h)/2[vbase]"
        )
        current_v = "[vbase]"
    else:  # Center crop
        filter_str = "[0:v]crop=ih*(9/16):ih:(iw-ow)/2:0,scale=1080:1920,setsar=1[vbase]"
        current_v = "[vbase]"
        
    filters.append(filter_str)
    
    # 2. Add top Hook Banner text if provided
    if clean_hook:
        banner_filter = (
            f"{current_v}drawtext=text='{clean_hook}':"
            "fontsize=36:fontcolor=white:font='Liberation Sans':"
            "box=1:boxcolor=black@0.7:boxborderw=14:"
            "x=(w-text_w)/2:y=60[vhook]"
        )
        filters.append(banner_filter)
        current_v = "[vhook]"
        
    # 3. Burn Subtitles if available
    if ass_subtitle_path and Path(ass_subtitle_path).exists():
        # Escape path for FFmpeg subtitles filter
        escaped_ass = str(Path(ass_subtitle_path).resolve()).replace('\\', '/').replace(':', '\\:')
        sub_filter = f"{current_v}subtitles='{escaped_ass}'[vfinal]"
        filters.append(sub_filter)
        current_v = "[vfinal]"
    else:
        # Pass through
        pass_filter = f"{current_v}null[vfinal]"
        filters.append(pass_filter)
        current_v = "[vfinal]"
        
    full_filter_complex = "; ".join(filters)
    
    cmd = [
        "ffmpeg",
        "-y",
        "-i", input_video,
        "-filter_complex", full_filter_complex,
        "-map", current_v,
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        str(out_path)
    ]
    
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=240
        )
        if proc.returncode != 0:
            return None, f"FFmpeg render error: {proc.stderr[-400:]}"
            
        if not out_path.exists() or out_path.stat().st_size == 0:
            return None, "FFmpeg finished but output file is missing or 0 bytes."
            
        return str(out_path), ""
    except subprocess.TimeoutExpired:
        return None, "FFmpeg render timed out after 4 minutes."
    except Exception as e:
        return None, f"FFmpeg execution failed: {str(e)}"
