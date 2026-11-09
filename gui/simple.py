"""Simple mode: one box, one button. For people who just want a cartoon.

Type a one-line story idea (the free local AI writer turns it into a script) or paste a full
script, choose Quick or Best quality, press "Make my cartoon". Everything else is automatic.
"""
from __future__ import annotations

import threading
from tkinter import messagebox

import customtkinter as ctk

from core.script_parser import ScriptParser, detect_language
from engines.background_painter import DOWNLOAD_MB as PAINTER_MB
from engines.background_painter import BackgroundPainter
from engines.script_writer import DOWNLOAD_MB, ScriptWriter, WriterError
from utils import user_prefs
from gui.components import ACCENT, ACCENT_HOVER, DANGER, MUTED, Card
from utils.user_prefs import estimate_minutes, human_duration

EXAMPLES = ["Leo saves a lost goat in the village", "Bilal's motorcycle breaks down and Ustad Akram helps",
            "The bullies learn to share at the park", "لیو اسکول میں بچوں کو صفائی کا سبق سکھاتا ہے"]


def looks_like_script(text: str) -> bool:
    p = ScriptParser().parse(text)
    return p.report.ok and len(p.all_dialogue_events()) >= 3


class SimpleView(ctk.CTkFrame):
    def __init__(self, app):
        super().__init__(app, fg_color="transparent")
        self.app = app
        self.writer = ScriptWriter()
        self.busy = False
        self.grid_columnconfigure(0, weight=1)
        card = Card(self)
        card.grid(row=0, column=0, sticky="nsew", padx=120, pady=10)
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(card, text="Make a cartoon", font=ctk.CTkFont(size=30, weight="bold")).grid(
            row=0, column=0, pady=(24, 2))
        ctk.CTkLabel(card, text="Write your story idea in one line — or paste a full script.",
                     text_color=MUTED, font=ctk.CTkFont(size=15)).grid(row=1, column=0)
        self.box = ctk.CTkTextbox(card, height=150, font=ctk.CTkFont(size=18), wrap="word",
                                  fg_color="#0b1220", border_width=1, border_color="#2a3244")
        self.box.grid(row=2, column=0, sticky="ew", padx=40, pady=(16, 6))
        self.box.bind("<KeyRelease>", lambda e: self._update_estimate())
        ex = ctk.CTkFrame(card, fg_color="transparent")
        ex.grid(row=3, column=0, pady=(0, 8))
        ctk.CTkLabel(ex, text="Try:", text_color=MUTED).pack(side="left", padx=4)
        for idea in EXAMPLES[:3]:
            ctk.CTkButton(ex, text=idea, height=26, fg_color="#1f2a3d", hover_color="#2f3c5a",
                          command=lambda i=idea: self._use_example(i)).pack(side="left", padx=3)
        opts = ctk.CTkFrame(card, fg_color="transparent")
        opts.grid(row=4, column=0, pady=6)
        ctk.CTkLabel(opts, text="Language").pack(side="left", padx=(0, 6))
        self.lang = ctk.CTkSegmentedButton(opts, values=["Urdu", "English"])
        self.lang.set("Urdu")
        self.lang.pack(side="left", padx=(0, 24))
        ctk.CTkLabel(opts, text="Speed").pack(side="left", padx=(0, 6))
        self.speed = ctk.CTkSegmentedButton(opts, values=["Quick", "Best quality"],
                                            command=lambda v: self._update_estimate())
        self.speed.set("Quick" if app.hw.recommended_quality == "preview" else "Best quality")
        self.speed.pack(side="left")
        self.estimate = ctk.CTkLabel(card, text="", text_color=MUTED, font=ctk.CTkFont(size=14))
        self.estimate.grid(row=5, column=0, pady=(6, 0))
        self.go = ctk.CTkButton(card, text="Make my cartoon", height=64, width=360, corner_radius=18,
                                font=ctk.CTkFont(size=22, weight="bold"), fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                command=self._make)
        self.go.grid(row=6, column=0, pady=16)
        self.bar = ctk.CTkProgressBar(card, height=16, progress_color=ACCENT)
        self.bar.set(0)
        self.bar.grid(row=7, column=0, sticky="ew", padx=60)
        self.status = ctk.CTkLabel(card, text="", font=ctk.CTkFont(size=15), wraplength=700)
        self.status.grid(row=8, column=0, pady=(8, 4))
        self.cancel = ctk.CTkButton(card, text="Stop", width=100, fg_color="#3a2228", hover_color=DANGER,
                                    command=self._cancel)
        done = ctk.CTkFrame(card, fg_color="transparent")
        done.grid(row=10, column=0, pady=(6, 24))
        self.watch = ctk.CTkButton(done, text="Watch video", height=44, width=200, state="disabled",
                                   font=ctk.CTkFont(size=16, weight="bold"), command=app._open_video)
        self.watch.pack(side="left", padx=8)
        self.folder = ctk.CTkButton(done, text="Open folder", height=44, width=160, state="disabled",
                                    fg_color="#253048", hover_color="#2f3c5a", command=app._open_folder)
        self.folder.pack(side="left", padx=8)
        self._update_estimate()

    # ---------------------------------------------------------------- helpers
    def quality(self) -> str:
        return "preview" if self.speed.get() == "Quick" else "standard"

    def _use_example(self, idea: str) -> None:
        self.box.delete("1.0", "end")
        self.box.insert("1.0", idea)
        self._update_estimate()

    def _update_estimate(self) -> None:
        text = self.box.get("1.0", "end").strip()
        seconds, lines = 100.0, 18
        if text and looks_like_script(text):
            p = ScriptParser().parse(text)
            from core.character_manager import CharacterRegistry
            from core.scene_manager import SceneManager

            SceneManager(CharacterRegistry()).enrich(p)
            seconds = max(60.0, sum(s.estimated_duration for s in p.scenes))
            lines = len(p.all_dialogue_events())
        minutes = estimate_minutes(seconds, self.quality(), lines)
        writer = "" if (not text or looks_like_script(text)) else " (+ 2–4 min to write the story)"
        self.estimate.configure(text=f"Takes {human_duration(minutes)} on this computer{writer}. "
                                     "You can leave it running — you'll get a notification when it's ready.")

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.go.configure(state="disabled" if busy else "normal", text="Working…" if busy else "Make my cartoon")
        if busy:
            self.cancel.grid(row=9, column=0, pady=4)
        else:
            self.cancel.grid_remove()

    def _cancel(self) -> None:
        self.app._cancel()
        self.status.configure(text="Stopping…")

    # ------------------------------------------------------------------ flow
    def _make(self) -> None:
        text = self.box.get("1.0", "end").strip()
        if not text:
            self.status.configure(text="Please type a story idea first.", text_color=DANGER)
            return
        self.watch.configure(state="disabled")
        self.folder.configure(state="disabled")
        self.app.settings.quality = self.quality()
        is_script = looks_like_script(text)
        need_writer = not is_script and not self.writer.is_installed()
        prefs = user_prefs.load()
        need_painter = (BackgroundPainter.available() and not BackgroundPainter.is_installed()
                        and not prefs.get("declined_backgrounds"))
        get_painter = False
        if need_writer or need_painter:
            items = []
            if need_writer:
                items.append(f"• AI story writer (turns your idea into a script): {DOWNLOAD_MB / 1000:.1f} GB")
            if need_painter:
                items.append(f"• AI background painter (beautiful scenery): {PAINTER_MB / 1000:.1f} GB")
            ok = messagebox.askyesno(
                "Free AI tools", "These free AI tools run on this computer (no internet needed after this):\n\n"
                + "\n".join(items) + "\n\nOne-time download. Download now?", parent=self)
            if not ok:
                if need_painter:
                    user_prefs.save(declined_backgrounds=True)
                if need_writer:
                    self.status.configure(text="Paste a full script instead, or allow the download to use "
                                               "story ideas.", text_color=MUTED)
                    return
            get_painter = ok and need_painter
        language = "ur" if (self.lang.get() == "Urdu" or detect_language(text) == "ur") else "en"
        self._set_busy(True)
        threading.Thread(target=self._prepare_thread, args=(text, language, is_script, get_painter),
                         daemon=True).start()

    def _prepare_thread(self, text: str, language: str, is_script: bool, get_painter: bool) -> None:
        q = self.app.queue

        def progress(frac: float, msg: str) -> None:
            q.put(("writer", (frac, msg)))

        try:
            if get_painter:
                BackgroundPainter.install(progress)
            if is_script:
                q.put(("writer_done", (text, False)))
                return
            if not self.writer.is_installed():
                self.writer.install(progress)
            q.put(("writer_done", (self.writer.write(text, language, progress=progress), True)))
        except (WriterError, OSError) as exc:
            q.put(("writer_error", str(exc)))
        except Exception as exc:  # download/network problems must reach the user, not vanish
            q.put(("writer_error", f"Download or AI writer problem: {exc}"))

    def on_writer(self, kind: str, payload) -> None:
        if kind == "writer":
            frac, msg = payload
            self.bar.set(frac * 0.1)
            self.status.configure(text=msg, text_color="#e2e8f0")
        elif kind == "writer_done":
            script, written = payload
            if written:
                self._review(script)
            else:
                self.status.configure(text="Making the cartoon…", text_color="#e2e8f0")
                self._start_video(script)
        else:
            self._set_busy(False)
            self.status.configure(text="✗ " + payload, text_color=DANGER)

    def _review(self, script: str) -> None:
        """Show the AI-written story (properly shaped Urdu) before the long render starts."""
        from gui.components import render_script_image

        self.status.configure(text="Your story is ready — please check it.", text_color="#e2e8f0")
        win = ctk.CTkToplevel(self)
        win.title("Check your story")
        win.geometry("980x720")
        win.transient(self.app)
        ctk.CTkLabel(win, text="Check your story", font=ctk.CTkFont(size=22, weight="bold")).pack(pady=(14, 2))
        ctk.CTkLabel(win, text="The AI writer can make small word mistakes. Read it once, then make the cartoon "
                               "or edit it in Studio mode.", text_color=MUTED).pack()
        frame = ctk.CTkScrollableFrame(win, fg_color="#0b1220")
        frame.pack(fill="both", expand=True, padx=16, pady=10)
        img = render_script_image(script, width=1400)
        w = 920
        self._review_img = ctk.CTkImage(light_image=img, dark_image=img, size=(w, int(img.height * w / img.width)))
        ctk.CTkLabel(frame, text="", image=self._review_img).pack()
        row = ctk.CTkFrame(win, fg_color="transparent")
        row.pack(pady=12)

        def make():
            win.destroy()
            self.status.configure(text="Making the cartoon…", text_color="#e2e8f0")
            self._start_video(script)

        def edit():
            win.destroy()
            self.app.editor.delete("1.0", "end")
            self.app.editor.insert("1.0", script)
            self.app._on_edit()
            self._set_busy(False)
            self.app._set_mode("Studio")

        def again():
            win.destroy()
            self._set_busy(False)
            self._make()

        ctk.CTkButton(row, text="Looks good — make the cartoon", height=44, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      font=ctk.CTkFont(size=16, weight="bold"), command=make).pack(side="left", padx=6)
        ctk.CTkButton(row, text="Edit first", height=44, fg_color="#253048", hover_color="#2f3c5a",
                      command=edit).pack(side="left", padx=6)
        ctk.CTkButton(row, text="Write it again", height=44, fg_color="#253048", hover_color="#2f3c5a",
                      command=again).pack(side="left", padx=6)
        win.protocol("WM_DELETE_WINDOW", edit)

    def _start_video(self, script: str) -> None:
        self.app.editor.delete("1.0", "end")
        self.app.editor.insert("1.0", script)  # also visible in Studio mode for editing
        self.app._on_edit()
        self._set_busy(True)
        if not self.app._generate():
            self._set_busy(False)
            self.status.configure(text="✗ The script has a problem — switch to Studio mode to see it.",
                                  text_color=DANGER)

    def on_progress(self, p) -> None:
        self.bar.set(max(0.0, min(1.0, 0.1 + 0.9 * p.percent / 100)))
        scene = f" — scene {p.scene} of {p.scene_count}" if p.scene else ""
        self.status.configure(text=f"{p.label}{scene}  ({p.percent:.0f}%)", text_color="#e2e8f0")

    def on_finished(self, res) -> None:
        self._set_busy(False)
        if res.ok:
            self.bar.set(1.0)
            self.status.configure(text="Your cartoon is ready!", text_color="#86efac")
            self.watch.configure(state="normal")
        else:
            self.status.configure(text="✗ " + (res.error or "Something went wrong"), text_color=DANGER)
        if res.episode_dir:
            self.folder.configure(state="normal")
