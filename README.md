# Gameplay Clipper

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![License: MIT](https://img.shields.io/badge/License-MIT-green)

Turn your gameplay recordings into captioned vertical clips, ready to upload
to YouTube Shorts, TikTok, Instagram Reels and Facebook.

## What it does

1. **Clip** — cut any moment out of a recording (`--start` / `--end`).
2. **Auto-caption** — transcribes the audio with Whisper (free, offline) and
   burns small bold captions into the bottom-centre of the video (Verdana by
   default; change it with `--font`, e.g. Arial, Impact).
3. **Resize** — exports vertical 9:16 (1080x1920) by default, so it fits
   Shorts / TikTok / Reels without black bars. Two ways to fill the frame:
   - `blur` (default): the full gameplay stays visible, with a blurred copy
     filling the sides — best when the HUD matters.
   - `crop`: fills the frame edge to edge, sides cut off — best for
     close-up moments.
4. **Background music** — mix any track you pick (`--music`) quietly under
   the game audio. The tool can't fetch trending songs for you — they are
   copyrighted and change daily — so bring your own file: a track you own,
   or royalty-free music (e.g. YouTube Audio Library).
5. **Best moments** — `--highlights 3` skips picking times by hand: it
   finds the loudest moments in the video (gunfights, explosions,
   reactions) and exports the top 3 as separate clips.

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
Browse). Pick the start / end (1 minute by default), platform, blur or
crop, and hit "Make clip". You can also pick a background music file (with a volume
slider), choose the caption font, or tick "Auto-pick best moments" and let it find the loudest
moments for you. While a clip is being made, a little robot edits it for
you — bobbing, blinking and snipping the film strip — next to a progress
bar. The File menu (Ctrl+O to open a video) and the status bar at the
bottom make it feel like a proper app. Drag & drop needs one extra package:

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

# Mix background music under the game audio (music at 20% volume)
python clip.py gameplay.mp4 --start 60 --end 90 --music my_track.mp3 --music-volume 0.2 --out clip.mp4

# Auto-pick the 3 best moments, 15 seconds each, no times needed
python clip.py gameplay.mp4 --highlights 3 --out best.mp4
# -> best_1.mp4, best_2.mp4, best_3.mp4

# Best moments, shorter, with music
python clip.py gameplay.mp4 --highlights 3 --highlight-length 10 --music my_track.mp3 --out best.mp4
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
| `--music` | Background music file (mp3/wav), mixed under the game audio |
| `--music-volume` | Music volume 0.0–1.0 (default 0.15) |
| `--highlights` | Auto-pick this many best moments instead of `--start`/`--end` |
| `--highlight-length` | Length of each auto highlight in seconds (default 60) |
| `--font` | Caption font, e.g. Verdana, Arial, Impact (default Verdana) |

Captions are small white bold text with a black outline, centred at the
bottom of the frame — the usual short-form look. The `.srt` file is kept in a temp folder; if you want
to edit captions by hand, run with `--model` once, grab the SRT, edit it,
and a future `--srt` option will burn your edited version in.

## How captions work

`faster-whisper` runs OpenAI's Whisper model locally on your CPU — no API
key, no upload, no cost. The `tiny` model is fast and fine for clear
commentary; `base` or `small` are more accurate if the game audio is loud.
First run downloads the model (~75 MB for tiny), then it's cached.

## Roadmap

- [x] Auto-highlight detection — finds the loudest / most exciting moments
      automatically instead of picking start/end by hand (`--highlights`)
- [x] Background music — mix a track of your choice under the game audio
      (`--music`)
- [ ] `--srt` flag — burn in your own hand-edited captions
- [ ] Web UI — drag a video in, drag the trim handles, download the clip
- [ ] Batch mode — cut several moments from one recording in one run
- [ ] Per-platform export — one command, outputs for Shorts + TikTok + Reels

## Notes

- Clips over 3 minutes will still export, but Shorts/TikTok/Reels cap
  videos at 3 minutes — keep moments short.
- Only download YouTube videos you own or have permission to reuse.
  The tool uses `yt-dlp` for this and nothing else.
