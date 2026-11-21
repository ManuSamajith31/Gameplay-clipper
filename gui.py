#!/usr/bin/env python3
"""
gameplay-clipper GUI — make clips without the terminal.

Paste a YouTube link, or drop / browse to a local recording, pick the
moment, and hit "Make clip". Runs the same pipeline as clip.py.

Drag & drop needs tkinterdnd2 (pip install tkinterdnd2). Without it, the
Browse button still works.
"""

import os
import queue
import sys
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))

from clip import (  # noqa: E402
    PRESETS,
    export_clip,
    fetch_source,
    find_highlights,
    mix_music,
    parse_time,
    probe_duration,
    transcribe_to_srt,
)

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    HAVE_DND = True
except ImportError:
    HAVE_DND = False


def ensure_tools_on_path() -> None:
    bindir = Path(sys.executable).parent
    path = os.environ.get("PATH", "")
    if str(bindir) not in path.split(os.pathsep):
        os.environ["PATH"] = str(bindir) + os.pathsep + path


def split_drop_data(data: str) -> list[str]:
    paths: list[str] = []
    current = ""
    in_braces = False
    for ch in data:
        if ch == "{":
            in_braces = True
        elif ch == "}":
            in_braces = False
        elif ch == " " and not in_braces:
            if current:
                paths.append(current)
                current = ""
        else:
            current += ch
    if current:
        paths.append(current)
    return paths


class ClipperApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Gameplay Clipper")
        self.root.geometry("560x660")
        self.root.minsize(480, 560)
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.result_queue: queue.Queue[tuple[bool, str]] = queue.Queue()
        self.running = False
        self.source_file: str | None = None
        self._build()
        self._poll_log()

    def _build(self) -> None:
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main, text="Gameplay Clipper",
                  font=("", 16, "bold")).pack(anchor="w")
        ttk.Label(main, text="Paste a YouTube link, or drop / pick a local recording."
                  ).pack(anchor="w")

        self.drop_label = ttk.Label(
            main, text="Drop a video file here", relief="solid",
            anchor="center", padding=28)
        self.drop_label.pack(fill=tk.X, pady=(10, 4))
        if HAVE_DND:
            self.drop_label.drop_target_register(DND_FILES)
            self.drop_label.dnd_bind("<<Drop>>", self._on_drop)
        else:
            self.drop_label.config(
                text="Drop a video file here\n"
                     "(drag & drop needs: pip install tkinterdnd2)")

        url_row = ttk.Frame(main)
        url_row.pack(fill=tk.X)
        ttk.Label(url_row, text="YouTube link:").pack(side=tk.LEFT)
        self.url_entry = ttk.Entry(url_row)
        self.url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))

        file_row = ttk.Frame(main)
        file_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(file_row, text="Browse video…",
                   command=self._browse_file).pack(side=tk.LEFT)
        self.file_label = ttk.Label(file_row, text="No file chosen")
        self.file_label.pack(side=tk.LEFT, padx=(8, 0))

        time_row = ttk.Frame(main)
        time_row.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(time_row, text="Start:").pack(side=tk.LEFT)
        self.start_entry = ttk.Entry(time_row, width=10)
        self.start_entry.insert(0, "0:30")
        self.start_entry.pack(side=tk.LEFT, padx=(4, 12))
        ttk.Label(time_row, text="End:").pack(side=tk.LEFT)
        self.end_entry = ttk.Entry(time_row, width=10)
        self.end_entry.insert(0, "0:45")
        self.end_entry.pack(side=tk.LEFT, padx=(4, 0))
        ttk.Label(time_row, text="(seconds or mm:ss)").pack(
            side=tk.LEFT, padx=(8, 0))

        opts = ttk.Frame(main)
        opts.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(opts, text="Platform:").pack(side=tk.LEFT)
        self.platform_var = tk.StringVar(value="tiktok")
        ttk.Combobox(opts, textvariable=self.platform_var,
                     values=sorted(PRESETS), width=10,
                     state="readonly").pack(side=tk.LEFT, padx=(4, 12))
        ttk.Label(opts, text="Fill:").pack(side=tk.LEFT)
        self.mode_var = tk.StringVar(value="blur")
        ttk.Combobox(opts, textvariable=self.mode_var,
                     values=["blur", "crop"], width=7,
                     state="readonly").pack(side=tk.LEFT, padx=(4, 12))
        self.captions_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="Captions",
                        variable=self.captions_var).pack(side=tk.LEFT)

        model_row = ttk.Frame(main)
        model_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(model_row, text="Caption model:").pack(side=tk.LEFT)
        self.model_var = tk.StringVar(value="tiny")
        ttk.Combobox(model_row, textvariable=self.model_var,
                     values=["tiny", "base", "small"], width=7,
                     state="readonly").pack(side=tk.LEFT, padx=(4, 0))
        ttk.Label(model_row,
                  text="tiny is fastest, small is most accurate").pack(
                      side=tk.LEFT, padx=(8, 0))

        music_row = ttk.Frame(main)
        music_row.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(music_row, text="Music:").pack(side=tk.LEFT)
        self.music_entry = ttk.Entry(music_row)
        self.music_entry.pack(side=tk.LEFT, fill=tk.X, expand=True,
                              padx=(6, 6))
        ttk.Button(music_row, text="Browse…",
                   command=self._browse_music).pack(side=tk.LEFT)
        self.music_volume = tk.Scale(
            music_row, from_=0, to=50, orient=tk.HORIZONTAL, length=120,
            label="Music volume %", showvalue=True)
        self.music_volume.set(15)
        self.music_volume.pack(side=tk.LEFT, padx=(6, 0))

        auto_row = ttk.Frame(main)
        auto_row.pack(fill=tk.X, pady=(6, 0))
        self.auto_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(auto_row, text="Auto-pick best moments",
                        variable=self.auto_var,
                        command=self._toggle_auto).pack(side=tk.LEFT)
        ttk.Label(auto_row, text="How many:").pack(side=tk.LEFT, padx=(8, 0))
        self.count_entry = ttk.Entry(auto_row, width=4)
        self.count_entry.insert(0, "3")
        self.count_entry.pack(side=tk.LEFT, padx=(4, 0))
        ttk.Label(auto_row, text="Length (s):").pack(side=tk.LEFT, padx=(8, 0))
        self.hlen_entry = ttk.Entry(auto_row, width=4)
        self.hlen_entry.insert(0, "15")
        self.hlen_entry.pack(side=tk.LEFT, padx=(4, 0))

        out_row = ttk.Frame(main)
        out_row.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(out_row, text="Save as:").pack(side=tk.LEFT)
        self.out_entry = ttk.Entry(out_row)
        self.out_entry.insert(0, "clip.mp4")
        self.out_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 6))
        ttk.Button(out_row, text="Browse…",
                   command=self._browse_out).pack(side=tk.LEFT)

        self.run_button = ttk.Button(main, text="Make clip",
                                     command=self._start_run)
        self.run_button.pack(fill=tk.X, pady=(12, 4))
        self.status_label = ttk.Label(main, text="Ready")
        self.status_label.pack(anchor="w")

        self.log = tk.Text(main, height=12, state=tk.DISABLED, wrap=tk.WORD)
        self.log.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

    def _on_drop(self, event) -> None:  # type: ignore[no-untyped-def]
        paths = split_drop_data(event.data)
        if paths:
            self._set_file(paths[0])

    def _browse_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose a gameplay recording",
            filetypes=[("Video files", "*.mp4 *.mkv *.mov *.avi *.webm"),
                       ("All files", "*.*")])
        if path:
            self._set_file(path)

    def _set_file(self, path: str) -> None:
        self.source_file = path
        self.file_label.config(text=Path(path).name)
        self.url_entry.delete(0, tk.END)

    def _browse_music(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose background music",
            filetypes=[("Audio files", "*.mp3 *.wav *.m4a *.ogg *.flac"),
                       ("All files", "*.*")])
        if path:
            self.music_entry.delete(0, tk.END)
            self.music_entry.insert(0, path)

    def _toggle_auto(self) -> None:
        state = tk.DISABLED if self.auto_var.get() else tk.NORMAL
        self.start_entry.config(state=state)
        self.end_entry.config(state=state)

    def _browse_out(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Save clip as", defaultextension=".mp4",
            filetypes=[("MP4 video", "*.mp4"), ("All files", "*.*")])
        if path:
            self.out_entry.delete(0, tk.END)
            self.out_entry.insert(0, path)

    def _log(self, message: str) -> None:
        self.log_queue.put(message)

    def _poll_log(self) -> None:
        try:
            while True:
                line = self.log_queue.get_nowait()
                self.log.config(state=tk.NORMAL)
                self.log.insert(tk.END, line + "\n")
                self.log.see(tk.END)
                self.log.config(state=tk.DISABLED)
        except queue.Empty:
            pass
        try:
            while True:
                ok, message = self.result_queue.get_nowait()
                self._finish(ok, message)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log)

    def _start_run(self) -> None:
        if self.running:
            return
        url = self.url_entry.get().strip()
        source = url or self.source_file
        if not source:
            messagebox.showerror(
                "No video",
                "Paste a YouTube link or choose a local video file first.")
            return
        auto = self.auto_var.get()
        start = end = 0.0
        highlights = 0
        highlight_len = 15.0
        if auto:
            try:
                highlights = int(self.count_entry.get().strip())
                highlight_len = float(self.hlen_entry.get().strip())
            except ValueError:
                messagebox.showerror(
                    "Bad number",
                    "How many / Length must be numbers.")
                return
            if highlights < 1 or highlight_len <= 0:
                messagebox.showerror(
                    "Bad number",
                    "How many must be at least 1 and Length above 0.")
                return
        else:
            try:
                start = parse_time(self.start_entry.get().strip())
                end = parse_time(self.end_entry.get().strip())
            except ValueError:
                messagebox.showerror(
                    "Bad time",
                    "Start / End must be seconds (83) or mm:ss (1:23).")
                return
            if end <= start:
                messagebox.showerror("Bad time", "End must be after Start.")
                return
            if end - start > 180:
                messagebox.showwarning(
                    "Long clip",
                    "Clips over 3 minutes still export, but Shorts / TikTok / "
                    "Reels cap videos at 3 minutes.")
        out = self.out_entry.get().strip()
        if not out:
            messagebox.showerror("No output", "Give the clip a file name.")
            return
        music = self.music_entry.get().strip() or None
        music_volume = self.music_volume.get() / 100

        self.running = True
        self.run_button.config(state=tk.DISABLED)
        self.status_label.config(text="Working…")
        self._log(f"Source: {source}")
        threading.Thread(
            target=self._run,
            args=(source, start, end, self.platform_var.get(),
                  self.mode_var.get(), self.captions_var.get(),
                  self.model_var.get(), out, music, music_volume,
                  highlights, highlight_len),
            daemon=True).start()

    def _run(self, source: str, start: float, end: float, platform: str,
             mode: str, captions: bool, model: str, out: str,
             music: str | None, music_volume: float,
             highlights: int, highlight_len: float) -> None:
        try:
            width, height = PRESETS[platform]
            with tempfile.TemporaryDirectory(prefix="clipper-") as tmp:
                workdir = Path(tmp)
                local = fetch_source(source, workdir)
                duration = probe_duration(str(local))
                if highlights:
                    starts = find_highlights(str(local), count=highlights,
                                             clip_len=highlight_len)
                    self._log(
                        f"Best moments: {[f'{s:.0f}s' for s in starts]}")
                    jobs = [(s, min(s + highlight_len, duration))
                            for s in starts]
                else:
                    if end > duration:
                        self._log(
                            f"Video is only {duration:.0f}s long — "
                            f"trimming end to {duration:.0f}s.")
                        end = duration
                    jobs = [(start, end)]
                out_path = Path(out)
                made: list[Path] = []
                for i, (job_start, job_end) in enumerate(jobs):
                    srt = None
                    if captions:
                        self._log("Transcribing captions…")
                        srt = transcribe_to_srt(local, job_start, job_end,
                                                model, workdir)
                        if srt is None:
                            self._log(
                                "No speech found — exporting without captions.")
                    out_i = out_path if len(jobs) == 1 else out_path.with_stem(
                        f"{out_path.stem}_{i + 1}")
                    self._log(f"Exporting clip {i + 1}/{len(jobs)}…")
                    export_clip(local, job_start, job_end, out_i,
                                width, height, mode, srt)
                    if music:
                        self._log("Mixing in music…")
                        mix_music(out_i, music, music_volume, out_i)
                    self._log(
                        f"Done -> {out_i}  ({width}x{height}, "
                        f"{job_end - job_start:.0f}s)")
                    made.append(out_i)
            if len(made) == 1:
                message = f"Saved: {made[0]}"
            else:
                message = f"Saved {len(made)} clips: {made[0]} …"
            self.result_queue.put((True, message))
        except SystemExit as exc:
            self.result_queue.put((False, f"Failed: {exc}"))
        except Exception as exc:  # noqa: BLE001 - show any failure in the UI
            self.result_queue.put((False, f"Failed: {exc}"))

    def _finish(self, ok: bool, message: str) -> None:
        self.running = False
        self.run_button.config(state=tk.NORMAL)
        self.status_label.config(text=message)
        if ok:
            messagebox.showinfo("Done", message)
        else:
            self._log(message)
            messagebox.showerror("Something went wrong", message)


def main() -> None:
    ensure_tools_on_path()
    root = TkinterDnD.Tk() if HAVE_DND else tk.Tk()
    ClipperApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
