---
title: AI Autonomous Video Clipper
emoji: 🎬
colorFrom: purple
colorTo: indigo
sdk: gradio
sdk_version: 4.44.0
app_file: app.py
pinned: false
---

# 🎬 Autonomous AI Video Clipper & Shorts Publisher

An end-to-end, 100% free autonomous pipeline for turning long YouTube streams and videos into viral 9:16 vertical YouTube Shorts with:
- **Automatic Channel Ingestion:** Monitors YouTube channels via public RSS feeds (zero API quota used for checking).
- **Instant AI Transcript Analysis:** Uses `youtube-transcript-api` and **Google Gemini 2.0 Flash** (free tier) to identify viral hooks, funny moments, and gameplay highlights.
- **Smart 2-Panel Split-Screen & 9:16 Editing:** FFmpeg-powered 2-panel layout (Facecam top + Gameplay bottom) or smart-blurred 9:16 frame.
- **Dynamic Kinetic Subtitles:** Burned-in, word-highlighted karaoke-style captions (Hormozi style).
- **Direct YouTube Upload:** Uploads ready-to-watch YouTube Shorts with viral titles, descriptions, and tags.
- **24/7 Autopilot Scheduler:** Built-in background worker running continuously on Hugging Face Spaces.
