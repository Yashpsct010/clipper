import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime

import gradio as gr
from apscheduler.schedulers.background import BackgroundScheduler

from config import (
    load_config,
    save_config,
    OUTPUT_DIR,
    PROCESSED_FILE,
    DATA_DIR
)
from pipeline.rss_monitor import (
    get_channel_id_from_url_or_handle,
    fetch_latest_channel_videos,
    load_processed_records
)
from pipeline.orchestrator import (
    process_youtube_video,
    run_autopilot_cycle
)
from pipeline.youtube_uploader import (
    is_youtube_authenticated,
    upload_short_to_youtube,
    save_client_secrets_content,
    save_token_content
)

# Global in-memory log buffer for the live web UI
ui_logs = []

def add_log(msg: str):
    timestamp = datetime.now().strftime("%H:%M:%S")
    formatted = f"[{timestamp}] {msg}"
    ui_logs.append(formatted)
    if len(ui_logs) > 300:
        ui_logs.pop(0)

# Initialize background scheduler for autonomous clipping
scheduler = BackgroundScheduler()

def scheduled_job():
    cfg = load_config()
    if cfg.get("autopilot_enabled", False):
        add_log("⚡ Scheduled Autopilot trigger running...")
        run_autopilot_cycle(log_callback=add_log)

def restart_scheduler(interval_minutes: int):
    scheduler.remove_all_jobs()
    scheduler.add_job(
        scheduled_job,
        'interval',
        minutes=max(5, interval_minutes),
        id='autopilot_job'
    )

init_cfg = load_config()
scheduler.add_job(
    scheduled_job,
    'interval',
    minutes=max(5, init_cfg.get("check_interval_minutes", 60)),
    id='autopilot_job'
)
scheduler.start()

# --- Gradio Callback Functions ---

def get_system_status_md():
    cfg = load_config()
    gemini_ok = "✅ Configured" if cfg.get("gemini_api_key") else "❌ Missing"
    channel = cfg.get("target_channel_id") or "Not Set"
    auto_status = "🟢 ACTIVE (24/7 Autopilot)" if cfg.get("autopilot_enabled") else "⚪ PAUSED (Manual Only)"
    yt_auth = "✅ Connected" if is_youtube_authenticated() else "⚠️ Not Connected (Local Saving Only)"
    
    return f"""
### System Status
- **Autopilot:** {auto_status}
- **Target Channel:** `{channel}`
- **Google Gemini AI:** {gemini_ok}
- **YouTube Upload:** {yt_auth}
- **Checking Frequency:** Every {cfg.get('check_interval_minutes', 60)} minutes
"""

def get_logs_text():
    if not ui_logs:
        return "No activity logged yet. System ready."
    return "\n".join(ui_logs[-60:])

def trigger_manual_autopilot():
    add_log("🚀 Manual check triggered by user...")
    res = run_autopilot_cycle(log_callback=add_log)
    status = res.get("status", "unknown")
    if status == "disabled":
        add_log("Note: Autopilot toggle is currently OFF in Settings.")
    elif status == "up_to_date":
        add_log("Channel check complete: No new unprocessed videos found.")
    elif status == "completed":
        add_log("Processing cycle completed successfully!")
    return get_system_status_md(), get_logs_text()

def run_manual_clip(
    video_url: str,
    max_clips: int,
    layout_mode: str,
    preset: str,
    custom_fc: str,
    custom_gp: str,
    burn_subs: bool
):
    if not video_url:
        return None, "Please provide a valid YouTube URL.", get_logs_text()
        
    cfg = load_config()
    if not cfg.get("gemini_api_key"):
        return None, "Error: Google Gemini API key is missing. Add it in Settings first.", get_logs_text()
        
    # Layout presets
    fc_coords = [1380, 40, 500, 380] # Top-Right default
    gp_coords = [160, 0, 1600, 1080] # Center default
    
    if preset == "Top-Left Facecam":
        fc_coords = [40, 40, 500, 380]
    elif preset == "Bottom-Right Facecam":
        fc_coords = [1380, 660, 500, 380]
    elif preset == "Bottom-Left Facecam":
        fc_coords = [40, 660, 500, 380]
    elif preset == "Custom Coordinates":
        try:
            fc_coords = [int(x.strip()) for x in custom_fc.split(",")]
            gp_coords = [int(x.strip()) for x in custom_gp.split(",")]
        except Exception:
            pass

    override_cfg = {
        "max_clips_per_video": int(max_clips),
        "layout_mode": layout_mode,
        "facecam_crop": fc_coords,
        "gameplay_crop": gp_coords,
        "burn_subtitles": burn_subs,
        "auto_upload": False # Manual tests are not automatically uploaded
    }
    
    add_log(f"Starting manual clip generation for: {video_url}")
    result = process_youtube_video(video_url, custom_config=override_cfg, log_callback=add_log)
    
    if not result.get("success"):
        return None, f"Failed: {result.get('error', 'Unknown error')}", get_logs_text()
        
    clips = result.get("clips", [])
    if not clips:
        return None, "No clips generated.", get_logs_text()
        
    # Return first rendered clip for preview
    first_clip = clips[0]
    video_path = first_clip["file_path"]
    details_md = f"""
### 🎬 Generated Short #{1} of {len(clips)}
- **Title:** `{first_clip['title']}`
- **Hook Headline:** `{first_clip['hook']}`
- **Viral Score:** **{first_clip['viral_score']}/100**
- **File:** `{first_clip['filename']}`

**Description:**
```
{first_clip['description']}
```
"""
    return video_path, details_md, get_logs_text()

def save_settings_ui(
    gemini_key: str,
    channel_input: str,
    interval: int,
    autopilot_on: bool,
    auto_upload_on: bool,
    privacy: str,
    layout_mode: str
):
    channel_id = get_channel_id_from_url_or_handle(channel_input) or channel_input.strip()
    
    new_cfg = {
        "gemini_api_key": gemini_key.strip(),
        "target_channel_id": channel_id,
        "check_interval_minutes": int(interval),
        "autopilot_enabled": bool(autopilot_on),
        "auto_upload": bool(auto_upload_on),
        "video_privacy": privacy,
        "layout_mode": layout_mode
    }
    
    save_config(new_cfg)
    restart_scheduler(int(interval))
    add_log("Configuration saved successfully.")
    return f"✅ Settings saved! Channel ID resolved to: {channel_id}", get_system_status_md()

def upload_credentials_file(file_obj, file_type: str):
    if file_obj is None:
        return "No file uploaded."
    try:
        content = Path(file_obj.name).read_text(encoding="utf-8")
        if file_type == "client_secrets":
            if save_client_secrets_content(content):
                return "✅ client_secrets.json successfully uploaded and saved!"
        elif file_type == "token":
            if save_token_content(content):
                return "✅ token.json successfully uploaded! YouTube is now connected."
        return "❌ Error: Invalid JSON content in file."
    except Exception as e:
        return f"❌ Upload error: {str(e)}"

# --- Build the Gradio UI ---

theme = gr.themes.Soft(
    primary_hue="purple",
    secondary_hue="indigo"
)

with gr.Blocks(title="Autonomous AI Video Clipper", theme=theme) as demo:
    gr.Markdown("""
    # 🎬 Autonomous AI Stream Clipper & Shorts Publisher
    Transform long YouTube livestreams & VODs into viral 9:16 YouTube Shorts on complete autopilot.
    """)
    
    status_display = gr.Markdown(value=get_system_status_md())
    
    with gr.Tabs():
        # --- TAB 1: AUTOPILOT DASHBOARD ---
        with gr.TabItem("🚀 24/7 Autopilot Dashboard"):
            with gr.Row():
                with gr.Column(scale=2):
                    gr.Markdown("### Autopilot Controls")
                    with gr.Row():
                        trigger_btn = gr.Button("⚡ Check Channel & Clip Now", variant="primary")
                        refresh_log_btn = gr.Button("🔄 Refresh Logs")
                    
                    gr.Markdown("### Real-Time Pipeline Logs")
                    log_output = gr.TextArea(
                        value=get_logs_text(),
                        lines=16,
                        max_lines=20,
                        interactive=False,
                        label="Live Execution Console"
                    )
                with gr.Column(scale=1):
                    gr.Markdown("""
                    ### How 24/7 Autopilot Works
                    1. Hugging Face Spaces keeps this worker running 24/7.
                    2. Checks your channel's public RSS feed every hour.
                    3. When a new stream drops, it fetches the transcript in 2 seconds.
                    4. Gemini AI pinpoints the top viral moments.
                    5. Downloads only those 45s sections via `yt-dlp`.
                    6. Creates 2-panel facecam + gameplay layout and burns kinetic captions.
                    7. Directly uploads the Short to your YouTube channel!
                    """)
                    
            trigger_btn.click(
                fn=trigger_manual_autopilot,
                outputs=[status_display, log_output]
            )
            refresh_log_btn.click(
                fn=get_logs_text,
                outputs=[log_output]
            )
            
        # --- TAB 2: MANUAL CLIP LAB ---
        with gr.TabItem("🧪 Manual Clip Lab (Test Any Video)"):
            gr.Markdown("Paste any YouTube stream or video link to immediately extract, reframe, and preview Shorts.")
            with gr.Row():
                with gr.Column(scale=1):
                    manual_url = gr.Textbox(
                        label="YouTube Video / Stream URL",
                        placeholder="https://www.youtube.com/watch?v=..."
                    )
                    manual_max_clips = gr.Slider(
                        minimum=1, maximum=5, value=2, step=1,
                        label="Number of Shorts to Extract"
                    )
                    manual_layout = gr.Dropdown(
                        choices=["split_screen", "blurred_background", "center_crop"],
                        value="split_screen",
                        label="9:16 Framing Mode"
                    )
                    manual_preset = gr.Dropdown(
                        choices=[
                            "Top-Right Facecam",
                            "Top-Left Facecam",
                            "Bottom-Right Facecam",
                            "Bottom-Left Facecam",
                            "Custom Coordinates"
                        ],
                        value="Top-Right Facecam",
                        label="Streamer Overlay Preset (for Split-Screen)"
                    )
                    with gr.Row():
                        custom_fc_box = gr.Textbox(
                            value="1380, 40, 500, 380",
                            label="Facecam [x, y, w, h]",
                            visible=True
                        )
                        custom_gp_box = gr.Textbox(
                            value="160, 0, 1600, 1080",
                            label="Gameplay [x, y, w, h]",
                            visible=True
                        )
                    manual_burn_subs = gr.Checkbox(
                        value=True,
                        label="Burn Animated Hormozi-Style Captions"
                    )
                    generate_btn = gr.Button("✨ Generate Shorts Preview", variant="primary")
                    
                with gr.Column(scale=1):
                    preview_video = gr.Video(label="Rendered 9:16 Short Preview")
                    clip_details = gr.Markdown("Generated clip information will appear here.")
                    
            generate_btn.click(
                fn=run_manual_clip,
                inputs=[
                    manual_url,
                    manual_max_clips,
                    manual_layout,
                    manual_preset,
                    custom_fc_box,
                    custom_gp_box,
                    manual_burn_subs
                ],
                outputs=[preview_video, clip_details, log_output]
            )
            
        # --- TAB 3: SETTINGS & CREDENTIALS ---
        with gr.TabItem("⚙️ Settings & Credentials"):
            gr.Markdown("Configure your free API keys, target channel, and YouTube connection.")
            cfg = load_config()
            
            with gr.Row():
                with gr.Column():
                    gr.Markdown("### Core Settings")
                    set_gemini = gr.Textbox(
                        value=cfg.get("gemini_api_key", ""),
                        label="Google Gemini API Key (Free)",
                        placeholder="AIzaSy...",
                        type="password",
                        info="Get your free API key at https://aistudio.google.com/"
                    )
                    set_channel = gr.Textbox(
                        value=cfg.get("target_channel_id", ""),
                        label="Target YouTube Channel (ID or Handle)",
                        placeholder="e.g. UC_x5XG1OV2P6uZZ5FSM9Ttw or @PewDiePie",
                        info="The channel whose new livestreams/videos will be auto-clipped."
                    )
                    set_interval = gr.Slider(
                        minimum=10, maximum=360, value=cfg.get("check_interval_minutes", 60), step=10,
                        label="Autopilot Check Interval (Minutes)"
                    )
                    set_layout = gr.Dropdown(
                        choices=["split_screen", "blurred_background", "center_crop"],
                        value=cfg.get("layout_mode", "split_screen"),
                        label="Default Layout Mode"
                    )
                    set_autopilot = gr.Checkbox(
                        value=cfg.get("autopilot_enabled", False),
                        label="Enable 24/7 Autopilot Scheduler"
                    )
                    set_upload = gr.Checkbox(
                        value=cfg.get("auto_upload", False),
                        label="Automatically Upload Rendered Shorts to YouTube"
                    )
                    set_privacy = gr.Radio(
                        choices=["private", "unlisted", "public"],
                        value=cfg.get("video_privacy", "private"),
                        label="Default Upload Privacy Status (Recommended: private or unlisted for review)"
                    )
                    save_settings_btn = gr.Button("💾 Save Configuration", variant="primary")
                    save_feedback = gr.Markdown("")
                    
                with gr.Column():
                    gr.Markdown("""
                    ### YouTube Channel Connection (OAuth)
                    To enable direct uploading to your YouTube channel:
                    1. Go to [Google Cloud Console](https://console.cloud.google.com/).
                    2. Enable the **YouTube Data API v3**.
                    3. Create an **OAuth 2.0 Client ID** (Desktop Application) and download `client_secrets.json`.
                    4. Upload it below, or generate `token.json` locally using `python auth_helper.py` and upload it.
                    """)
                    
                    upload_token_file = gr.File(label="Upload token.json (Fastest)")
                    token_btn = gr.Button("Link token.json")
                    token_feedback = gr.Markdown("")
                    
                    upload_secrets_file = gr.File(label="Upload client_secrets.json")
                    secrets_btn = gr.Button("Upload client_secrets.json")
                    secrets_feedback = gr.Markdown("")
                    
            save_settings_btn.click(
                fn=save_settings_ui,
                inputs=[
                    set_gemini,
                    set_channel,
                    set_interval,
                    set_autopilot,
                    set_upload,
                    set_privacy,
                    set_layout
                ],
                outputs=[save_feedback, status_display]
            )
            
            token_btn.click(
                fn=lambda f: upload_credentials_file(f, "token"),
                inputs=[upload_token_file],
                outputs=[token_feedback]
            )
            
            secrets_btn.click(
                fn=lambda f: upload_credentials_file(f, "client_secrets"),
                inputs=[upload_secrets_file],
                outputs=[secrets_feedback]
            )

if __name__ == "__main__":
    demo.queue().launch()
