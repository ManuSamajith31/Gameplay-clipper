# Gameplay Clipper

Turn your gameplay recordings into captioned vertical clips, ready to upload
to YouTube Shorts, TikTok, Instagram Reels and Facebook.

## What it does

1. **Clip** — cut any moment out of a recording (`--start` / `--end`).
2. **Auto-caption** — transcribes the audio with Whisper (free, offline) and
   burns bold short-form captions into the video.
3. **Resize** — exports vertical 9:16 (1080x1920) by default, so it fits
   Shorts / TikTok / Reels without black bars. Two ways to fill the frame:
   - `blur` (default): the full gameplay stays visible, with a blurred copy
     filling the sides — best when the HUD matters.
   - `crop`: fills the frame edge to edge, sides cut off — best for
     close-up moments.

Input can be a local recording, or a YouTube URL — use your own uploads
(or videos you have the rights to), not other people's content.

## Setup

Needs **ffmpeg** and **Python 3.10+**.

```bash
# macOS
brew install ffmpeg python
# Windows (winget)
winget install Gyan.FFmpeg Python.Python.3.12
# Ubuntu / Debian
sudo apt install ffmpeg python3 python3-venv

# then, inside this folder:
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## GUI (no terminal)

Prefer buttons to commands? Run the simple window:

```bash
python gui.py
```

Paste a YouTube link, or drag a video file onto the window (or use
Browse). Pick the start / end, platform, blur or crop, and hit
"Make clip". Drag & drop needs one extra package:

```bash
pip install tkinterdnd2
```

Without it, the window still works — just use Browse instead of
dragging.

## Usage

```bash
# 30 seconds of a local recording, captions on, vertical for TikTok
python clip.py gameplay.mp4 --start 83 --end 113 --out clip.mp4

# Times also work as mm:ss
python clip.py gameplay.mp4 --start 1:23 --end 1:53 --out clip.mp4

# Crop to fill the frame instead of blurred sides
python clip.py gameplay.mp4 --start 1:23 --end 1:53 --mode crop --out clip.mp4

# Square 1:1 for a Facebook feed post, no captions
python clip.py gameplay.mp4 --start 60 --end 90 --format 1:1 --no-captions --out clip.mp4

# Keep it landscape 16:9, just trim + captions
python clip.py gameplay.mp4 --start 10 --end 40 --format 16:9 --out clip.mp4

# Your own YouTube gameplay video as the source
python clip.py "https://www.youtube.com/watch?v=XXXX" --start 60 --end 90 --out clip.mp4
```

| Flag | What it does |
| --- | --- |
| `--start` / `--end` | Clip boundaries, seconds (`83`) or `mm:ss` (`1:23`) |
| `--out` | Output file, e.g. `clip.mp4` |
| `--platform` | `tiktok` / `shorts` / `reels` / `facebook` (all 1080x1920), `square`, `landscape` |
| `--format` | Size override: `9:16`, `1:1`, `16:9` |
| `--mode` | `blur` (default) or `crop` |
| `--no-captions` | Skip auto-captions |
| `--model` | Whisper model: `tiny` (fast, default), `base`, `small` (better, slower) |

Captions are white bold text with a black outline, bottom-centre — the
usual short-form look. The `.srt` file is kept in a temp folder; if you want
to edit captions by hand, run with `--model` once, grab the SRT, edit it,
and a future `--srt` option will burn your edited version in.

## How captions work

`faster-whisper` runs OpenAI's Whisper model locally on your CPU — no API
key, no upload, no cost. The `tiny` model is fast and fine for clear
commentary; `base` or `small` are more accurate if the game audio is loud.
First run downloads the model (~75 MB for tiny), then it's cached.

## Roadmap

- [ ] Auto-highlight detection — find the loudest / most exciting moments
      automatically instead of picking start/end by hand
- [ ] `--srt` flag — burn in your own hand-edited captions
- [ ] Web UI — drag a video in, drag the trim handles, download the clip
- [ ] Batch mode — cut several moments from one recording in one run
- [ ] Per-platform export — one command, outputs for Shorts + TikTok + Reels

## Notes

- Clips over 3 minutes will still export, but Shorts/TikTok/Reels cap
  videos at 3 minutes — keep moments short.
- Only download YouTube videos you own or have permission to reuse.
  The tool uses `yt-dlp` for this and nothing else.
