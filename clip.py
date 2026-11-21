#!/usr/bin/env python3
"""
gameplay-clipper — turn gameplay recordings into captioned vertical clips
for YouTube Shorts, TikTok, Instagram Reels and Facebook.

What it does
------------
1. Takes a local gameplay recording, or a YouTube URL (your own uploads).
2. Cuts the moment you pick (--start / --end).
3. Auto-captions the audio with Whisper (free, runs offline on your machine)
   and burns the captions into the video, short-form style.
4. Resizes to vertical 9:16 (1080x1920) so it's ready to upload.

Requirements: ffmpeg + ffprobe on your PATH, Python 3.10+.
Install the Python deps with:  pip install -r requirements.txt

Examples
--------
  # Clip 30 seconds of a local recording, captions on, vertical for TikTok
  python clip.py gameplay.mp4 --start 83 --end 113 --out clip.mp4

  # Sharper export: upscale the finished clip x2 (2160x3840 vertical)
  python clip.py gameplay.mp4 --start 83 --end 113 --upscale 2 --out clip.mp4

  # Same, but crop to fill the frame instead of blurred sides
  python clip.py gameplay.mp4 --start 1:23 --end 1:53 --mode crop --out clip.mp4

  # Your own YouTube gameplay video, no captions, square for Facebook
  python clip.py "https://www.youtube.com/watch?v=XXXX" --start 60 --end 90 \\
      --format 1:1 --no-captions --out clip.mp4

  # Keep the original 16:9 landscape, just trim + captions
  python clip.py gameplay.mp4 --start 10 --end 40 --format 16:9 --out clip.mp4
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path




PRESETS = {
    "shorts": (1080, 1920),
    "tiktok": (1080, 1920),
    "reels": (1080, 1920),
    "facebook": (1080, 1920),
    "square": (1080, 1080),
    "landscape": (1920, 1080),
}

def caption_style(font: str = "Verdana") -> str:
    return (
        f"FontName={font},FontSize=18,PrimaryColour=&HFFFFFF,"
        "OutlineColour=&H000000,BorderStyle=1,Outline=2,Shadow=0,"
        "Bold=1,Alignment=2,MarginV=30"
    )





def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a command, print it, and fail loudly unless check=False."""
    print(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if check and result.returncode != 0:
        tail = "\n".join(result.stderr.strip().splitlines()[-5:])
        raise RuntimeError(
            f"Command failed (exit {result.returncode}): {' '.join(cmd)}\n{tail}")
    return result


def parse_time(value: str) -> float:
    """Accept seconds (83), mm:ss (1:23) or hh:mm:ss (0:01:23)."""
    parts = value.strip().split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        raise argparse.ArgumentTypeError(f"bad time: {value!r} (use seconds or mm:ss)")
    total = 0.0
    for n in nums:
        total = total * 60 + n
    if total < 0:
        raise argparse.ArgumentTypeError("time can't be negative")
    return total


def probe_duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def probe_size(path: str) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height",
         "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True,
    )
    w, h = out.stdout.strip().split(",")
    return int(w), int(h)





def window_loudness(video: str, start: float, length: float) -> float:
    result = subprocess.run(
        ["ffmpeg", "-ss", str(start), "-t", str(length),
         "-i", video, "-vn", "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, check=False,
    )
    match = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", result.stderr)
    return float(match.group(1)) if match else -91.0


def find_highlights(video: str, window: float = 5.0,
                    clip_len: float = 15.0, count: int = 3) -> list[float]:
    duration = probe_duration(video)
    scored: list[tuple[float, float]] = []
    start = 0.0
    while start < duration:
        scored.append((window_loudness(
            video, start, min(window, duration - start)), start))
        start += window
    scored.sort(key=lambda item: (-item[0], item[1]))
    picked: list[float] = []
    for _, moment in scored:
        clip_start = max(0.0, moment + window / 2 - clip_len / 2)
        clip_start = min(clip_start, max(0.0, duration - clip_len))
        if all(abs(clip_start - other) >= clip_len for other in picked):
            picked.append(clip_start)
        if len(picked) == count:
            break
    return sorted(picked)


def fetch_source(source: str, workdir: Path) -> Path:
    if os.path.isfile(source):
        return Path(source)
    if source.startswith(("http://", "https://")):
        print("Downloading video with yt-dlp (use your own uploads only)…")
        target = workdir / "source.%(ext)s"
        ytdlp = shutil.which("yt-dlp") or str(
            Path(sys.executable).parent / "yt-dlp")
        run([ytdlp, "-f", "bv*[height<=1080]+ba/b[height<=1080]",
             "--merge-output-format", "mp4",
             "-o", str(target), source])
        files = sorted(workdir.glob("source.*"))
        if not files:
            sys.exit("yt-dlp didn't produce a file — check the URL.")
        return files[0]
    sys.exit(f"Can't find file or URL: {source}")





def transcribe_to_srt(video: Path, start: float, end: float,
                      model: str, workdir: Path) -> Path | None:
    """Transcribe the clipped audio and write an .srt file. None if no speech."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("! faster-whisper not installed — skipping captions "
              "(pip install -r requirements.txt to enable them).")
        return None

    audio = workdir / "clip_audio.wav"
    run(["ffmpeg", "-y", "-v", "error", "-ss", str(start), "-to", str(end),
         "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(audio)])

    print(f"Transcribing with Whisper model {model!r} (first run downloads it)…")
    whisper = WhisperModel(model, device="cpu", compute_type="int8")



    import numpy as np
    pcm = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(audio),
         "-f", "f32le", "-ac", "1", "-ar", "16000", "-"],
        capture_output=True, check=True,
    ).stdout
    samples = np.frombuffer(pcm, dtype=np.float32)
    segments, _info = whisper.transcribe(samples, beam_size=5)

    lines: list[str] = []
    for i, seg in enumerate(segments, 1):
        text = seg.text.strip()
        if not text:
            continue
        lines.append(f"{i}\n{fmt_srt_time(seg.start)} --> {fmt_srt_time(seg.end)}\n{text}\n")

    if not lines:
        print("! No speech detected in this clip — no captions burned in.")
        return None

    srt = workdir / "captions.srt"
    srt.write_text("\n".join(lines), encoding="utf-8")
    print(f"Captions: {len(lines)} lines -> {srt}")
    return srt


def fmt_srt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"





def build_filter(width: int, height: int, mode: str, srt: Path | None,
                 font: str = "Verdana") -> str:
    """Video filter chain: vertical resize, then caption burn-in."""
    if width * 9 == height * 16:

        vf = f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos," \
             f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
    elif mode == "crop":
        vf = (f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
              f"crop={width}:{height}")
    else:
        vf = (
            f"split[a][b];"
            f"[a]scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={width}:{height},gblur=sigma=40[bg];"
            f"[b]scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2"
        )
    if srt is not None:

        srt_escaped = (str(srt).replace("\\", "/").replace(":", "\\:")
                       .replace("'", "\\'"))
        vf += f",subtitles='{srt_escaped}':force_style='{caption_style(font)}'"
    return vf


def export_clip(source: Path, start: float, end: float, out: Path,
                width: int, height: int, mode: str, srt: Path | None,
                font: str = "Verdana") -> None:
    vf = build_filter(width, height, mode, srt, font)
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start), "-to", str(end),
        "-i", str(source),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart",
        str(out),
    ]
    run(cmd)
    print(f"\nDone -> {out}  ({width}x{height}, {end - start:.0f}s)")


def mix_music(clip: Path, music: str, volume: float, out: Path) -> None:
    tmp = out.with_suffix(".music.mp4")
    run([
        "ffmpeg", "-y",
        "-i", str(clip),
        "-stream_loop", "-1", "-i", music,
        "-filter_complex",
        f"[0:a]volume=1[a0];[1:a]volume={volume}[a1];"
        "[a0][a1]amix=inputs=2:duration=first:dropout_transition=0[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart",
        str(tmp),
    ])
    tmp.replace(out)
    print(f"Music mixed in -> {out} (music at {volume:.0%})")





def main() -> None:
    ap = argparse.ArgumentParser(
        description="Clip gameplay into a captioned vertical short.")
    ap.add_argument("source", help="local video file, or a YouTube URL (your own video)")
    ap.add_argument("--start", default=None, type=parse_time,
                    help="clip start — seconds (83) or mm:ss (1:23)")
    ap.add_argument("--end", default=None, type=parse_time,
                    help="clip end — seconds or mm:ss")
    ap.add_argument("--out", required=True, help="output file, e.g. clip.mp4")
    ap.add_argument("--highlights", default=0, type=int,
                    help="auto-pick this many best moments instead of --start/--end")
    ap.add_argument("--highlight-length", default=60.0, type=float,
                    help="length of each auto highlight in seconds (default: 60)")
    ap.add_argument("--platform", default="tiktok", choices=sorted(PRESETS),
                    help="preset size (default: tiktok = 1080x1920)")
    ap.add_argument("--format", default=None,
                    help="override size: 9:16, 1:1 or 16:9")
    ap.add_argument("--upscale", default=1, type=int,
                    help="export at N times the preset size, e.g. 2 = 2160x3840 "
                         "vertical (sharper, bigger file)")
    ap.add_argument("--mode", default="blur", choices=["blur", "crop"],
                    help="blur: keep full frame with blurred sides (default); "
                         "crop: fill the frame, edges cut off")
    ap.add_argument("--no-captions", action="store_true",
                    help="skip auto-captions")
    ap.add_argument("--model", default="tiny",
                    help="Whisper model: tiny, base, small (bigger = better, slower)")
    ap.add_argument("--font", default="Verdana",
                    help="caption font, e.g. Verdana, Arial, Impact (default: Verdana)")
    ap.add_argument("--music", default=None,
                    help="background music file (mp3/wav), mixed under the game audio")
    ap.add_argument("--music-volume", default=0.15, type=float,
                    help="background music volume, 0.0-1.0 (default: 0.15)")
    args = ap.parse_args()

    if args.highlights:
        clip_len = args.highlight_length
    else:
        if args.start is None or args.end is None:
            ap.error("--start and --end are required unless --highlights is set")
        if args.end <= args.start:
            ap.error("--end must be after --start")
        if args.end - args.start > 180:
            print("! Clip is over 3 minutes — Shorts/TikTok/Reels cap at 3 min. "
                  "It'll still export, but check the platform limit.")
        clip_len = args.end - args.start

    width, height = PRESETS[args.platform]
    if args.format:
        fmt = args.format.replace(" ", "")
        width, height = {"9:16": (1080, 1920), "1:1": (1080, 1080),
                         "16:9": (1920, 1080)}.get(fmt) or ap.error(
            "--format must be 9:16, 1:1 or 16:9")
    if args.upscale < 1:
        ap.error("--upscale must be 1 or more")
    width *= args.upscale
    height *= args.upscale

    with tempfile.TemporaryDirectory(prefix="clipper-") as tmp:
        workdir = Path(tmp)
        source = fetch_source(args.source, workdir)
        duration = probe_duration(str(source))
        if args.highlights:
            starts = find_highlights(str(source), count=args.highlights,
                                     clip_len=clip_len)
            print(f"Best moments: {[f'{s:.0f}s' for s in starts]}")
            jobs = [(s, min(s + clip_len, duration)) for s in starts]
        else:
            end = args.end
            if end > duration:
                print(f"! Video is only {duration:.0f}s long — trimming --end to {duration:.0f}s.")
                end = duration
            jobs = [(args.start, end)]

        out_path = Path(args.out)
        for i, (start, end) in enumerate(jobs):
            srt = None
            if not args.no_captions:
                srt = transcribe_to_srt(source, start, end, args.model, workdir)
            out = out_path if len(jobs) == 1 else out_path.with_stem(
                f"{out_path.stem}_{i + 1}")
            export_clip(source, start, end, out, width, height, args.mode, srt,
                        args.font)
            if args.music:
                mix_music(out, args.music, args.music_volume, out)


if __name__ == "__main__":
    main()
