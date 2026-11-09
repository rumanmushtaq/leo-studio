"""Main window: paste script -> choose folder -> Generate 3D Cartoon."""
from __future__ import annotations

import json
import os
import platform
import queue
import subprocess
import threading
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from core.character_manager import CharacterRegistry
from core.generation_controller import GenerationController, GenerationResult
from core.script_parser import detect_language
from gui.components import (ACCENT, ACCENT_HOVER, DANGER, MUTED, Card, SectionTitle, UrduPreview,
                            render_script_image)
from gui.characters import CharacterWindow
from gui.simple import SimpleView
from gui.progress import ProgressPanel
from models.hardware_detector import detect
from models.model_manager import model_status
from utils.notify import notify
from utils import user_prefs
from utils.config import ASSETS_DIR, OUTPUT_DIR, PROJECT_ROOT, GenerationSettings

SAMPLE_SCRIPT = ASSETS_DIR / "scripts" / "leo_episode_001.txt"
PROJECTS_DIR = PROJECT_ROOT / "projects"
APP_ICON_PNG = ASSETS_DIR / "icon.png"
APP_ICON_ICO = ASSETS_DIR / "icon.ico"


def open_path(path: Path) -> None:
    """Open a file or folder with the OS default application."""
    if platform.system() == "Windows":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif platform.system() == "Darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class AdvancedSettings(ctk.CTkToplevel):
    """Optional settings kept out of the main screen."""

    def __init__(self, app: "StudioApp"):
        super().__init__(app)
        self.app = app
        self.title("Advanced settings")
        self.geometry("640x760")
        self.transient(app)
        s = app.settings
        pad = {"padx": 18, "pady": 6}
        ctk.CTkLabel(self, text="Advanced settings", font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", **pad)

        ctk.CTkLabel(self, text="Voice engine", anchor="w").pack(anchor="w", **pad)
        self.voice = ctk.CTkSegmentedButton(self, values=["auto", "mms", "espeak", "manual"])
        self.voice.set(s.voice_backend)
        self.voice.pack(anchor="w", padx=18)
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", **pad)
        self.manual = ctk.CTkEntry(row, placeholder_text="Manual audio folder (s01_e001.wav or 001.wav …)")
        if s.manual_audio_dir:
            self.manual.insert(0, str(s.manual_audio_dir))
        self.manual.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(row, text="Browse", width=80, command=self._pick_manual).pack(side="left", padx=6)

        self.episode = ctk.CTkEntry(self, placeholder_text="Episode folder name (optional)")
        if s.episode_name:
            self.episode.insert(0, s.episode_name)
        self.episode.pack(fill="x", **pad)
        self.music = ctk.CTkSwitch(self, text="Background music (original, generated)")
        self.music.select() if s.music else self.music.deselect()
        self.music.pack(anchor="w", **pad)
        self.gpu = ctk.CTkSwitch(self, text="Use NVIDIA GPU with Cycles for 'High' quality (if available)")
        self.gpu.select() if s.use_gpu else self.gpu.deselect()
        self.gpu.pack(anchor="w", **pad)
        self.keep = ctk.CTkSwitch(self, text="Keep temporary files")
        self.keep.select() if s.keep_temp else self.keep.deselect()
        self.keep.pack(anchor="w", **pad)

        ctk.CTkLabel(self, text="Render engine", font=ctk.CTkFont(weight="bold")).pack(anchor="w", **pad)
        self.engine = ctk.CTkSegmentedButton(self, values=["Blender 3D (this PC)", "AI video (ComfyUI server)"])
        self.engine.set("AI video (ComfyUI server)" if s.render_engine == "ai" else "Blender 3D (this PC)")
        self.engine.pack(anchor="w", padx=18)
        crow = ctk.CTkFrame(self, fg_color="transparent")
        crow.pack(fill="x", **pad)
        self.comfy = ctk.CTkEntry(crow, placeholder_text="http://192.168.1.20:8188")
        self.comfy.insert(0, s.comfy_url)
        self.comfy.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(crow, text="Test connection", width=130, command=self._test_comfy).pack(side="left", padx=6)
        self.comfy_status = ctk.CTkLabel(self, text="AI video needs a PC with an NVIDIA GPU running ComfyUI "
                                                   "(see assets/comfy_workflows/README.md).",
                                         text_color=MUTED, anchor="w", justify="left", wraplength=560)
        self.comfy_status.pack(anchor="w", **pad)
        self.ai_lips = ctk.CTkSwitch(self, text="AI lip-sync (LatentSync) on dialogue shots")
        self.ai_lips.select() if s.ai_lipsync else self.ai_lips.deselect()
        self.ai_lips.pack(anchor="w", **pad)

        ctk.CTkLabel(self, text="Local AI models", font=ctk.CTkFont(weight="bold")).pack(anchor="w", **pad)
        box = ctk.CTkTextbox(self, height=150, wrap="word")
        for m in model_status():
            state = "ready" if m["downloaded"] else "not downloaded" if m["integrated"] else "not integrated"
            box.insert("end", f"• {m['purpose']} — {m['repo']}\n   {m['size_mb']} MB · {m['license']} · {state}\n"
                              f"   {m['note']}\n")
        box.configure(state="disabled")
        box.pack(fill="both", expand=True, **pad)
        ctk.CTkButton(self, text="Save", command=self._save, fg_color=ACCENT, hover_color=ACCENT_HOVER).pack(
            anchor="e", **pad)

    def _test_comfy(self) -> None:
        from engines.ai_video.comfy_client import ComfyClient, ComfyError

        self.comfy_status.configure(text="Connecting…")
        self.update_idletasks()
        try:
            self.comfy_status.configure(text="✓ " + ComfyClient(self.comfy.get().strip(), timeout=8).describe(),
                                        text_color="#86efac")
        except ComfyError as exc:
            self.comfy_status.configure(text="✗ " + str(exc), text_color=DANGER)

    def _pick_manual(self) -> None:
        d = filedialog.askdirectory(parent=self)
        if d:
            self.manual.delete(0, "end")
            self.manual.insert(0, d)

    def _save(self) -> None:
        s = self.app.settings
        s.voice_backend = self.voice.get()
        s.manual_audio_dir = Path(self.manual.get()) if self.manual.get().strip() else None
        s.episode_name = self.episode.get().strip() or None
        s.music = bool(self.music.get())
        s.use_gpu = bool(self.gpu.get())
        s.keep_temp = bool(self.keep.get())
        s.render_engine = "ai" if self.engine.get().startswith("AI") else "blender"
        s.comfy_url = self.comfy.get().strip() or s.comfy_url
        s.ai_lipsync = bool(self.ai_lips.get())
        self.destroy()


class StudioApp(ctk.CTk):
    def __init__(self):
        # className = WM_CLASS on Linux, so the dock groups the window under the launcher icon
        super().__init__(className="leo3dstudio")
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title("LEO 3D AI CARTOON STUDIO")
        self._set_icon()
        self.geometry("1280x860")
        self.minsize(1080, 760)
        self.configure(fg_color="#0f141f")
        self.settings = GenerationSettings(output_dir=OUTPUT_DIR)
        self.hw = detect()
        self.settings.quality = self.hw.recommended_quality
        self.queue: queue.Queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.result: GenerationResult | None = None
        self._build()
        self.after(100, self._poll)

    def _set_icon(self) -> None:
        try:
            if platform.system() == "Windows" and APP_ICON_ICO.exists():
                self.iconbitmap(str(APP_ICON_ICO))
            elif APP_ICON_PNG.exists():
                from PIL import ImageTk

                self._icon = ImageTk.PhotoImage(file=str(APP_ICON_PNG))
                self.iconphoto(True, self._icon)
        except Exception:  # a missing icon must never stop the app
            pass

    # ------------------------------------------------------------------ layout
    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=3, uniform="cols")
        self.grid_columnconfigure(1, weight=2, uniform="cols")
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=24, pady=(18, 8))
        ctk.CTkLabel(header, text="LEO 3D AI CARTOON STUDIO",
                     font=ctk.CTkFont(size=28, weight="bold")).pack(side="left")
        ctk.CTkLabel(header, text="  Paste a script · choose a folder · get a 3D animated cartoon",
                     text_color=MUTED, font=ctk.CTkFont(size=13)).pack(side="left", pady=(8, 0))
        ctk.CTkButton(header, text="Advanced…", width=110, fg_color="#253048", hover_color="#2f3c5a",
                      command=lambda: AdvancedSettings(self)).pack(side="right")
        ctk.CTkButton(header, text="Characters…", width=120, fg_color="#253048", hover_color="#2f3c5a",
                      command=lambda: CharacterWindow(self)).pack(side="right", padx=8)
        self.mode_btn = ctk.CTkSegmentedButton(header, values=["Simple", "Studio"], command=self._set_mode)
        self.mode_btn.pack(side="right", padx=8)

        left = Card(self)
        self.left = left
        left.grid(row=1, column=0, sticky="nsew", padx=(24, 10), pady=8)
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(1, weight=1)
        top = ctk.CTkFrame(left, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 6))
        SectionTitle(top, "Cartoon script (Urdu or English)").pack(side="left")
        ctk.CTkButton(top, text="Load Leo sample", width=130, fg_color="#253048", hover_color="#2f3c5a",
                      command=self._load_sample).pack(side="right")
        ctk.CTkButton(top, text="Save project", width=110, fg_color="#253048", hover_color="#2f3c5a",
                      command=self._save_project).pack(side="right", padx=(6, 0))
        ctk.CTkButton(top, text="Open…", width=80, fg_color="#253048", hover_color="#2f3c5a",
                      command=self._open_script).pack(side="right", padx=6)
        ctk.CTkButton(top, text="Check script", width=110, fg_color="#253048", hover_color="#2f3c5a",
                      command=self._validate).pack(side="right")
        self.tabs = ctk.CTkTabview(left, fg_color="#0b1220", command=self._on_tab)
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=16)
        edit_tab = self.tabs.add("Edit")
        prev_tab = self.tabs.add("Urdu preview")
        edit_tab.grid_columnconfigure(0, weight=1)
        edit_tab.grid_rowconfigure(0, weight=1)
        prev_tab.grid_columnconfigure(0, weight=1)
        prev_tab.grid_rowconfigure(0, weight=1)
        self.editor = ctk.CTkTextbox(edit_tab, wrap="word", font=ctk.CTkFont(family="Noto Naskh Arabic", size=16),
                                     fg_color="#0b1220", border_width=0, undo=True)
        self.editor.grid(row=0, column=0, sticky="nsew")
        self.preview_scroll = ctk.CTkScrollableFrame(prev_tab, fg_color="#0b1220")
        self.preview_scroll.grid(row=0, column=0, sticky="nsew")
        self.preview_scroll.grid_columnconfigure(0, weight=1)
        self.preview_img_label = ctk.CTkLabel(self.preview_scroll, text="")
        self.preview_img_label.grid(row=0, column=0, sticky="n")
        self._preview_img = None
        self.editor.tag_config("rtl", justify="right")
        self.editor.bind("<KeyRelease>", self._on_edit)
        self.editor.bind("<ButtonRelease>", self._on_edit)
        self.editor.bind("<<Paste>>", lambda e: self.after(50, self._on_edit))
        self.preview = UrduPreview(left, width=640, height=56)
        self.preview.grid(row=2, column=0, sticky="ew", padx=16, pady=(8, 4))
        self.preview.show("")
        self.script_info = ctk.CTkLabel(left, text="", text_color=MUTED, anchor="w", justify="left", wraplength=640)
        self.script_info.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 14))

        right = ctk.CTkFrame(self, fg_color="transparent")
        self.right = right
        right.grid(row=1, column=1, sticky="nsew", padx=(10, 24), pady=8)
        right.grid_columnconfigure(0, weight=1)

        out = Card(right)
        out.grid(row=0, column=0, sticky="ew")
        out.grid_columnconfigure(0, weight=1)
        SectionTitle(out, "Output folder").grid(row=0, column=0, sticky="w", padx=16, pady=(14, 4))
        self.out_label = ctk.CTkLabel(out, text=str(self.settings.output_dir), anchor="w", text_color=MUTED,
                                      wraplength=380, justify="left")
        self.out_label.grid(row=1, column=0, sticky="ew", padx=16)
        ctk.CTkButton(out, text="Browse…", width=100, command=self._pick_output).grid(row=1, column=1, padx=16)
        qrow = ctk.CTkFrame(out, fg_color="transparent")
        qrow.grid(row=2, column=0, columnspan=2, sticky="ew", padx=16, pady=(10, 14))
        ctk.CTkLabel(qrow, text="Quality").pack(side="left")
        self.quality = ctk.CTkSegmentedButton(qrow, values=["preview", "standard", "high"],
                                              command=lambda v: setattr(self.settings, "quality", v))
        self.quality.set(self.settings.quality)
        self.quality.pack(side="left", padx=10)

        self.generate_btn = ctk.CTkButton(right, text="Generate 3D Cartoon", height=56, corner_radius=14,
                                          font=ctk.CTkFont(size=20, weight="bold"), fg_color=ACCENT,
                                          hover_color=ACCENT_HOVER, command=self._generate)
        self.generate_btn.grid(row=1, column=0, sticky="ew", pady=12)
        self.cancel_btn = ctk.CTkButton(right, text="Cancel", height=36, fg_color="#3a2228", hover_color=DANGER,
                                        command=self._cancel, state="disabled")
        self.cancel_btn.grid(row=2, column=0, sticky="ew")

        self.progress = ProgressPanel(right)
        self.progress.grid(row=3, column=0, sticky="ew", pady=12)

        res = Card(right)
        res.grid(row=4, column=0, sticky="ew")
        res.grid_columnconfigure(0, weight=1)
        SectionTitle(res, "Final video").grid(row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(14, 4))
        self.video_label = ctk.CTkLabel(res, text="Not generated yet", anchor="w", text_color=MUTED,
                                        wraplength=420, justify="left")
        self.video_label.grid(row=1, column=0, columnspan=2, sticky="ew", padx=16)
        self.play_btn = ctk.CTkButton(res, text="Open video", state="disabled", command=self._open_video)
        self.play_btn.grid(row=2, column=0, sticky="ew", padx=(16, 6), pady=14)
        self.folder_btn = ctk.CTkButton(res, text="Open output folder", state="disabled", fg_color="#253048",
                                        hover_color="#2f3c5a", command=self._open_folder)
        self.folder_btn.grid(row=2, column=1, sticky="ew", padx=(6, 16), pady=14)

        hw = self.hw
        gpu = hw.gpus[0] if hw.gpus else "no GPU"
        status = (f"{hw.cpu_model} · {hw.ram_total_gb:.0f} GB RAM · {gpu} · "
                  f"{hw.blender_version or 'Blender missing'} · FFmpeg {'ok' if hw.ffmpeg_path else 'missing'}")
        self.status = ctk.CTkLabel(self, text=status, text_color=MUTED, anchor="w", font=ctk.CTkFont(size=11))
        self.status.grid(row=2, column=0, columnspan=2, sticky="ew", padx=24, pady=(0, 10))
        if hw.warnings:
            self.progress.show_error("Startup check:\n• " + "\n• ".join(hw.warnings))
        self.simple = SimpleView(self)
        self._set_mode(user_prefs.load().get("mode", "Simple"))

    # ----------------------------------------------------------------- actions
    def _script(self) -> str:
        return self.editor.get("1.0", "end").strip()

    def _on_tab(self) -> None:
        if self.tabs.get() == "Urdu preview":
            img = render_script_image(self._script() or " ")
            w = max(400, self.preview_scroll.winfo_width() - 30)
            h = int(img.height * w / img.width)
            self._preview_img = ctk.CTkImage(light_image=img, dark_image=img, size=(w, h))
            self.preview_img_label.configure(image=self._preview_img)

    def _on_edit(self, _event=None) -> None:
        line = self.editor.get("insert linestart", "insert lineend")
        self.preview.show(line)
        # right-align Urdu lines in the editor
        self.editor.tag_remove("rtl", "1.0", "end")
        last = int(self.editor.index("end-1c").split(".")[0])
        for i in range(1, last + 1):
            if detect_language(self.editor.get(f"{i}.0", f"{i}.end")) == "ur":
                self.editor.tag_add("rtl", f"{i}.0", f"{i}.end")

    def _load_sample(self) -> None:
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", SAMPLE_SCRIPT.read_text(encoding="utf-8"))
        self._on_edit()
        self._validate()

    def _open_script(self) -> None:
        f = filedialog.askopenfilename(initialdir=str(PROJECTS_DIR),
                                       filetypes=[("Script or project", "*.txt *.leo.json"), ("All", "*.*")])
        if not f:
            return
        if f.endswith(".json"):
            proj = json.loads(Path(f).read_text(encoding="utf-8"))
            text = proj.get("script", "")
            st = proj.get("settings", {})
            self.settings.quality = st.get("quality", self.settings.quality)
            self.quality.set(self.settings.quality)
            if st.get("output_dir"):
                self.settings.output_dir = Path(st["output_dir"])
                self.out_label.configure(text=st["output_dir"])
            self.settings.episode_name = st.get("episode_name")
            self.settings.voice_backend = st.get("voice_backend", self.settings.voice_backend)
            self.settings.music = st.get("music", self.settings.music)
            self.settings.render_engine = st.get("render_engine", self.settings.render_engine)
            self.settings.comfy_url = st.get("comfy_url", self.settings.comfy_url)
        else:
            text = Path(f).read_text(encoding="utf-8")
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", text)
        self._on_edit()
        self._validate()

    def _save_project(self) -> None:
        """Script + settings as projects/<name>.leo.json, to reopen and regenerate later."""
        PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        f = filedialog.asksaveasfilename(initialdir=str(PROJECTS_DIR), defaultextension=".leo.json",
                                         initialfile=(self.settings.episode_name or "my_cartoon") + ".leo.json",
                                         filetypes=[("Leo project", "*.leo.json")])
        if not f:
            return
        st = self.settings
        data = {"format": "leo-project-1", "script": self._script(),
                "settings": {"quality": st.quality, "output_dir": str(st.output_dir), "episode_name": st.episode_name,
                             "voice_backend": st.voice_backend, "music": st.music,
                             "render_engine": st.render_engine, "comfy_url": st.comfy_url}}
        Path(f).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self.script_info.configure(text=f"Project saved: {f}", text_color="#86efac")

    def _validate(self) -> bool:
        text = self._script()
        ctrl = GenerationController(self.settings)
        parsed = ctrl.parse(text, CharacterRegistry())
        if not parsed.report.ok:
            self.script_info.configure(text="✗ " + " ".join(parsed.report.errors), text_color=DANGER)
            return False
        chars = sorted({c for s in parsed.scenes for c in s.characters})
        lines = len(parsed.all_dialogue_events())
        est = sum(s.estimated_duration for s in parsed.scenes)
        msg = (f"✓ {len(parsed.scenes)} scenes · {lines} dialogue/narration lines · characters: {', '.join(chars)}"
               f" · estimated ≈ {est:.0f} s")
        if parsed.report.warnings:
            msg += "\n⚠ " + "\n⚠ ".join(parsed.report.warnings[:4])
        self.script_info.configure(text=msg, text_color="#86efac" if not parsed.report.warnings else "#fde68a")
        return True

    def _pick_output(self) -> None:
        d = filedialog.askdirectory(initialdir=str(self.settings.output_dir))
        if d:
            self.settings.output_dir = Path(d)
            self.out_label.configure(text=d)

    def _set_mode(self, mode: str) -> None:
        """Simple = one box + one button; Studio = full editor and settings."""
        if mode == "Simple":
            self.left.grid_remove()
            self.right.grid_remove()
            self.simple.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=8)
        else:
            self.simple.grid_remove()
            self.left.grid()
            self.right.grid()
        self.mode_btn.set(mode)
        user_prefs.save(mode=mode)

    def _generate(self) -> bool:
        if self.worker and self.worker.is_alive():
            return False
        if not self._validate():
            if self.mode_btn.get() == "Studio":
                messagebox.showerror("Script problem", "Please fix the script first (see message under the editor).")
            return False
        self.cancel_event.clear()
        self.progress.reset()
        self.generate_btn.configure(state="disabled", text="Generating…")
        self.cancel_btn.configure(state="normal")
        self.play_btn.configure(state="disabled")
        self.folder_btn.configure(state="disabled")
        text = self._script()

        def work():
            ctrl = GenerationController(self.settings, on_progress=lambda p: self.queue.put(("progress", p)),
                                        cancel_event=self.cancel_event)
            self.queue.put(("done", ctrl.run(text)))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()
        return True

    def _cancel(self) -> None:
        self.cancel_event.set()
        self.cancel_btn.configure(state="disabled", text="Cancelling…")

    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "progress":
                    self.progress.update_progress(payload)
                    self.simple.on_progress(payload)
                elif kind == "done":
                    self._finished(payload)
                elif kind.startswith("writer"):
                    self.simple.on_writer(kind, payload)
        except queue.Empty:
            pass
        self.after(150, self._poll)

    def _finished(self, res: GenerationResult) -> None:
        self.result = res
        self.simple.on_finished(res)
        msg = "Your cartoon is ready!" if res.ok else "Generation stopped: " + (res.error or "error")[:120]
        notify("Leo 3D AI Cartoon Studio", msg, str(APP_ICON_PNG))
        self.bell()
        self.deiconify()
        self.lift()
        self.generate_btn.configure(state="normal", text="Generate 3D Cartoon")
        self.cancel_btn.configure(state="disabled", text="Cancel")
        if res.episode_dir:
            self.folder_btn.configure(state="normal")
        if res.ok and res.video:
            secs = res.report.get("video_details", {}).get("duration") or 0.0
            self.progress.finished(True, "Done ✓")
            self.video_label.configure(text=f"{res.video}\n{secs:.1f} s · 1280×720 · 24 fps · H.264/AAC",
                                       text_color="#e2e8f0")
            self.play_btn.configure(state="normal")
        else:
            self.progress.finished(False, "Stopped" if res.error and "cancel" in res.error.lower() else "Failed")
            self.progress.show_error(res.error or "Unknown error")
            if res.video and Path(res.video).exists():
                self.video_label.configure(text=str(res.video))
                self.play_btn.configure(state="normal")

    def _open_video(self) -> None:
        if self.result and self.result.video:
            open_path(self.result.video)

    def _open_folder(self) -> None:
        if self.result and self.result.episode_dir:
            open_path(self.result.episode_dir)


def run_app() -> None:
    app = StudioApp()
    app.mainloop()
