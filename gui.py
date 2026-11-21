#!/usr/bin/env python3
"""
gameplay-clipper GUI — make clips without the terminal.

Paste a YouTube link, or drop / browse to a local recording, pick the
moment, and hit "Make clip". Runs the same pipeline as clip.py.

Drag & drop needs tkinterdnd2 (pip install tkinterdnd2). Without it, the
Browse button still works.
"""

import os
import math
import queue
import sys
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

APP_VERSION = "1.2"

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
        self.root.geometry("620x880")
        self.root.minsize(540, 720)
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.result_queue: queue.Queue[tuple[bool, str]] = queue.Queue()
        self.running = False
        self.source_file: str | None = None
        self._dots = 0
        self._anim = 0
        self._bob_prev = 0
        self._pupil_prev = 0
        self._film_dx = 0
        self._blinking = False
        self._style()
        self._build_menu()
        self._build()
        self._draw_robot()
        self._poll_log()

    def _style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Title.TLabel", font=("", 20, "bold"),
                        foreground="#1d3557")
        style.configure("Sub.TLabel", foreground="#5a6b7a")
        style.configure("TLabelframe.Label", font=("", 10, "bold"),
                        foreground="#1d3557")
        style.configure("Accent.TButton", font=("", 11, "bold"),
                        foreground="white", background="#1f9d63", padding=8)
        style.map("Accent.TButton",
                  background=[("active", "#178a55"),
                              ("disabled", "#9db8a9")])
        style.configure("Drop.TLabel", background="#eaf6ee",
                        foreground="#1d3557", font=("", 11))

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open video…", accelerator="Ctrl+O",
                              command=self._browse_file)
        file_menu.add_command(label="Save clip as…",
                              command=self._browse_out)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.destroy)
        menubar.add_cascade(label="File", menu=file_menu)
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About Gameplay Clipper…",
                              command=self._about)
        menubar.add_cascade(label="Help", menu=help_menu)
        self.root.bind_all("<Control-o>", lambda _e: self._browse_file())

    def _about(self) -> None:
        messagebox.showinfo(
            "About Gameplay Clipper",
            f"Gameplay Clipper {APP_VERSION}\n\n"
            "Turn gameplay into Shorts, TikTok & Reels.\n"
            "Clip, auto-caption, add music and pick the best\n"
            "moments — in one click.")

    def _build(self) -> None:
        statusbar = ttk.Frame(self.root, relief="sunken", padding=(6, 2))
        statusbar.pack(side=tk.BOTTOM, fill=tk.X)
        self.statusbar_left = ttk.Label(statusbar, text="Ready")
        self.statusbar_left.pack(side=tk.LEFT)
        ttk.Label(statusbar,
                  text=f"Gameplay Clipper {APP_VERSION}").pack(side=tk.RIGHT)

        main = ttk.Frame(self.root, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        banner = tk.Frame(main, bg="#1d3557")
        banner.pack(fill=tk.X, pady=(0, 10))
        tk.Label(banner, text="Gameplay Clipper", font=("", 18, "bold"),
                 fg="white", bg="#1d3557").pack(side=tk.LEFT, padx=12, pady=8)
        tk.Label(banner, text="Shorts · TikTok · Reels", font=("", 10),
                 fg="#b8c7d9", bg="#1d3557").pack(side=tk.LEFT, padx=(4, 0),
                                                 pady=(14, 8))

        video_frame = ttk.LabelFrame(main, text="1 · Video", padding=8)
        video_frame.pack(fill=tk.X, pady=(0, 8))
        self.drop_label = ttk.Label(
            video_frame, text="Drop a video file here", style="Drop.TLabel",
            relief="solid", anchor="center", padding=24)
        self.drop_label.pack(fill=tk.X, pady=(0, 6))
        if HAVE_DND:
            self.drop_label.drop_target_register(DND_FILES)
            self.drop_label.dnd_bind("<<Drop>>", self._on_drop)
        else:
            self.drop_label.config(
                text="Drop a video file here\n"
                     "(drag & drop needs: pip install tkinterdnd2)")

        url_row = ttk.Frame(video_frame)
        url_row.pack(fill=tk.X)
        ttk.Label(url_row, text="YouTube link:").pack(side=tk.LEFT)
        self.url_entry = ttk.Entry(url_row)
        self.url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))

        file_row = ttk.Frame(video_frame)
        file_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(file_row, text="Browse video…",
                   command=self._browse_file).pack(side=tk.LEFT)
        self.file_label = ttk.Label(file_row, text="No file chosen")
        self.file_label.pack(side=tk.LEFT, padx=(8, 0))

        clip_frame = ttk.LabelFrame(main, text="2 · Clip", padding=8)
        clip_frame.pack(fill=tk.X, pady=(0, 8))
        time_row = ttk.Frame(clip_frame)
        time_row.pack(fill=tk.X)
        ttk.Label(time_row, text="Start:").pack(side=tk.LEFT)
        self.start_entry = ttk.Entry(time_row, width=10)
        self.start_entry.insert(0, "0:00")
        self.start_entry.pack(side=tk.LEFT, padx=(4, 12))
        ttk.Label(time_row, text="End:").pack(side=tk.LEFT)
        self.end_entry = ttk.Entry(time_row, width=10)
        self.end_entry.insert(0, "1:00")
        self.end_entry.pack(side=tk.LEFT, padx=(4, 0))
        ttk.Label(time_row, text="(seconds or mm:ss)").pack(
            side=tk.LEFT, padx=(8, 0))

        auto_row = ttk.Frame(clip_frame)
        auto_row.pack(fill=tk.X, pady=(8, 0))
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
        self.hlen_entry.insert(0, "60")
        self.hlen_entry.pack(side=tk.LEFT, padx=(4, 0))

        style_frame = ttk.LabelFrame(main, text="3 · Look & sound", padding=8)
        style_frame.pack(fill=tk.X, pady=(0, 8))
        opts = ttk.Frame(style_frame)
        opts.pack(fill=tk.X)
        ttk.Label(opts, text="Platform:").pack(side=tk.LEFT)
        self.platform_var = tk.StringVar(value="tiktok")
        ttk.Combobox(opts, textvariable=self.platform_var,
                     values=sorted(PRESETS), width=10,
                     state="readonly").pack(side=tk.LEFT, padx=(4, 12))
        ttk.Label(opts, text="Fill:").pack(side=tk.LEFT)
        self.mode_var = tk.StringVar(value="blur")
        ttk.Combobox(opts, textvariable=self.mode_var,
                     values=["blur", "crop"], width=7,
                     state="readonly").pack(side=tk.LEFT, padx=(4, 0))

        font_row = ttk.Frame(style_frame)
        font_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(font_row, text="Caption font:").pack(side=tk.LEFT)
        self.font_var = tk.StringVar(value="Verdana")
        ttk.Combobox(font_row, textvariable=self.font_var,
                     values=["Verdana", "Arial", "Trebuchet MS", "Tahoma",
                             "Impact", "Georgia"],
                     width=13, state="readonly").pack(
                         side=tk.LEFT, padx=(4, 12))
        ttk.Label(font_row, text="Model:").pack(side=tk.LEFT)
        self.model_var = tk.StringVar(value="tiny")
        ttk.Combobox(font_row, textvariable=self.model_var,
                     values=["tiny", "base", "small"], width=7,
                     state="readonly").pack(side=tk.LEFT, padx=(4, 0))
        ttk.Label(font_row,
                  text="tiny is fastest").pack(side=tk.LEFT, padx=(8, 0))
        self.captions_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(font_row, text="Captions",
                        variable=self.captions_var).pack(
                            side=tk.LEFT, padx=(8, 0))

        music_row = ttk.Frame(style_frame)
        music_row.pack(fill=tk.X, pady=(8, 0))
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

        save_frame = ttk.LabelFrame(main, text="4 · Save", padding=8)
        save_frame.pack(fill=tk.X)
        out_row = ttk.Frame(save_frame)
        out_row.pack(fill=tk.X)
        ttk.Label(out_row, text="Save as:").pack(side=tk.LEFT)
        self.out_entry = ttk.Entry(out_row)
        self.out_entry.insert(0, "clip.mp4")
        self.out_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 6))
        ttk.Button(out_row, text="Browse…",
                   command=self._browse_out).pack(side=tk.LEFT)

        quality_row = ttk.Frame(save_frame)
        quality_row.pack(fill=tk.X, pady=(8, 0))
        self.upscale_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(quality_row,
                        text="Sharper export (upscale ×2)",
                        variable=self.upscale_var).pack(side=tk.LEFT)

        work_row = ttk.Frame(save_frame)
        work_row.pack(fill=tk.X, pady=(10, 0))
        self.robot_canvas = tk.Canvas(work_row, width=140, height=110,
                                      bg="#f7f7f7", highlightthickness=0)
        self.robot_canvas.pack(side=tk.LEFT)
        right = ttk.Frame(work_row)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0))

        self.run_button = ttk.Button(right, text="✦  Make clip",
                                     style="Accent.TButton",
                                     command=self._start_run)
        self.run_button.pack(fill=tk.X)
        self.progress = ttk.Progressbar(right, mode="indeterminate")
        self.progress.pack(fill=tk.X, pady=(8, 0))
        self.status_label = ttk.Label(right, text="Ready")
        self.status_label.pack(anchor="w", pady=(6, 0))

        ttk.Label(main, text="Activity", font=("", 10, "bold")).pack(
            anchor="w", pady=(8, 0))
        self.log = tk.Text(main, height=8, state=tk.DISABLED, wrap=tk.WORD)
        self.log.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

    def _draw_robot(self, frame: int = 0) -> None:
        canvas = self.robot_canvas
        canvas.delete("all")
        green = "#2ea36b"
        dark = "#1e7a4c"
        bob = [0, -2, -3, -2, 0, 2, 3, 2][frame % 8]
        pupil_dx = [0, 2, 0, -2][frame % 4]
        blink = frame % 28 in (0, 1)
        ball = "#ffd166" if (frame // 8) % 2 else "#f4a259"

        film_dx = -(frame * 2 % 12)
        canvas.create_rectangle(-12 + film_dx, 92, 152 + film_dx, 104,
                                fill="#333333", outline="")
        for x in range(-12, 152, 12):
            canvas.create_rectangle(x + 4 + film_dx, 96, x + 8 + film_dx, 100,
                                    fill="white", outline="")

        canvas.create_line(70, 22 + bob, 70, 12 + bob, width=2, fill=dark)
        canvas.create_oval(66, 5 + bob, 74, 13 + bob, fill=ball, outline="")
        canvas.create_oval(48, 22 + bob, 92, 56 + bob, fill=green,
                           outline=dark, width=2)
        if blink:
            canvas.create_line(57, 37 + bob, 67, 37 + bob, width=2,
                               fill="#1d3557")
            canvas.create_line(73, 37 + bob, 83, 37 + bob, width=2,
                               fill="#1d3557")
        else:
            canvas.create_oval(57, 32 + bob, 67, 42 + bob, fill="white",
                               outline="")
            canvas.create_oval(73, 32 + bob, 83, 42 + bob, fill="white",
                               outline="")
            canvas.create_oval(60 + pupil_dx, 35 + bob, 66 + pupil_dx,
                               41 + bob, fill="#1d3557", outline="")
            canvas.create_oval(76 + pupil_dx, 35 + bob, 82 + pupil_dx,
                               41 + bob, fill="#1d3557", outline="")
        canvas.create_arc(60, 42 + bob, 80, 54 + bob, start=200, extent=140,
                          style=tk.ARC, outline="#1d3557", width=2)
        canvas.create_rectangle(52, 56 + bob, 88, 82 + bob, fill=green,
                                outline=dark, width=2)
        canvas.create_rectangle(62, 63 + bob, 78, 73 + bob, fill="#d8f3e3",
                                outline="")
        canvas.create_line(52, 62 + bob, 40, 70 + bob, width=3, fill=dark)
        canvas.create_line(88, 62 + bob, 100, 70 + bob, width=3, fill=dark)
        canvas.create_oval(37, 67 + bob, 43, 73 + bob, fill=green,
                           outline=dark)
        pivot = (104, 70 + bob)
        angle = 12 if (frame // 2) % 2 == 0 else -12
        for base in (45, -45):
            rad = math.radians(base + angle * (1 if base > 0 else -1))
            dx = 8 * math.cos(rad)
            dy = 8 * math.sin(rad)
            canvas.create_line(pivot[0] - dx, pivot[1] - dy,
                               pivot[0] + dx, pivot[1] + dy, width=2,
                               fill="#5a6b7a")

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
        self.statusbar_left.config(text=f"Source: {Path(path).name}")
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
        if self.running:
            self._dots = (self._dots + 1) % 4
            self.status_label.config(
                text=f"Robot is editing your clip{'.' * self._dots}")
            self._anim += 1
            self._draw_robot(self._anim)
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
        highlight_len = 60.0
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
        self.progress.start(12)
        self.status_label.config(text="Robot is editing your clip…")
        self.statusbar_left.config(text="Working…")
        self._log(f"Source: {source}")
        threading.Thread(
            target=self._run,
            args=(source, start, end, self.platform_var.get(),
                  self.mode_var.get(), self.captions_var.get(),
                  self.model_var.get(), out, music, music_volume,
                  highlights, highlight_len, self.font_var.get(),
                  self.upscale_var.get()),
            daemon=True).start()

    def _run(self, source: str, start: float, end: float, platform: str,
             mode: str, captions: bool, model: str, out: str,
             music: str | None, music_volume: float,
             highlights: int, highlight_len: float, font: str,
             upscale: bool) -> None:
        try:
            width, height = PRESETS[platform]
            if upscale:
                width *= 2
                height *= 2
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
                                width, height, mode, srt, font)
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
        self.progress.stop()
        self._draw_robot(0)
        self.run_button.config(state=tk.NORMAL)
        self.status_label.config(text=message)
        self.statusbar_left.config(text=message)
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
