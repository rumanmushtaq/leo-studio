"""Progress panel: stage, scene, real percentage, messages and errors."""
from __future__ import annotations

import customtkinter as ctk

from core.generation_controller import STAGES, Progress
from gui.components import ACCENT, DANGER, MUTED, Card, SectionTitle


class ProgressPanel(Card):
    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.grid_columnconfigure(0, weight=1)
        SectionTitle(self, "Generation progress").grid(row=0, column=0, sticky="w", padx=16, pady=(14, 4))
        self.stage = ctk.CTkLabel(self, text="Idle", anchor="w", font=ctk.CTkFont(size=15, weight="bold"))
        self.stage.grid(row=1, column=0, sticky="ew", padx=16)
        self.bar = ctk.CTkProgressBar(self, height=14, progress_color=ACCENT)
        self.bar.set(0)
        self.bar.grid(row=2, column=0, sticky="ew", padx=16, pady=8)
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.grid(row=3, column=0, sticky="ew", padx=16)
        row.grid_columnconfigure(1, weight=1)
        self.percent = ctk.CTkLabel(row, text="0 %", font=ctk.CTkFont(size=22, weight="bold"))
        self.percent.grid(row=0, column=0, sticky="w")
        self.scene = ctk.CTkLabel(row, text="", text_color=MUTED, anchor="e")
        self.scene.grid(row=0, column=1, sticky="e")
        self.detail = ctk.CTkLabel(self, text="", text_color=MUTED, anchor="w", justify="left", wraplength=520)
        self.detail.grid(row=4, column=0, sticky="ew", padx=16)
        self.steps = ctk.CTkLabel(self, text=self._steps_text(None), text_color=MUTED, anchor="w", justify="left",
                                  font=ctk.CTkFont(size=11))
        self.steps.grid(row=5, column=0, sticky="ew", padx=16, pady=(6, 4))
        self.error = ctk.CTkTextbox(self, height=70, text_color=DANGER, fg_color="#1f1418", wrap="word")
        self.error.grid(row=6, column=0, sticky="ew", padx=16, pady=(4, 14))
        self.error.grid_remove()

    @staticmethod
    def _steps_text(current: str | None) -> str:
        keys = [k for k, _, _ in STAGES]
        idx = keys.index(current) if current in keys else -1
        dots = "".join("●" if i < idx else "◉" if i == idx else "○" for i in range(len(keys)))
        return f"{dots}   step {idx + 1 if idx >= 0 else 0} of {len(keys)}"

    def update_progress(self, p: Progress) -> None:
        self.stage.configure(text=p.label)
        self.bar.set(max(0.0, min(1.0, p.percent / 100)))
        self.percent.configure(text=f"{p.percent:.1f} %")
        self.scene.configure(text=f"Scene {p.scene} of {p.scene_count}" if p.scene else "")
        counts = f"{p.stage_done}/{p.stage_total}  " if p.stage_total else ""
        self.detail.configure(text=f"{counts}{p.message}")
        self.steps.configure(text=self._steps_text(p.stage))

    def reset(self) -> None:
        self.stage.configure(text="Starting…")
        self.bar.set(0)
        self.percent.configure(text="0 %")
        self.scene.configure(text="")
        self.detail.configure(text="")
        self.hide_error()

    def show_error(self, msg: str) -> None:
        self.error.grid()
        self.error.configure(state="normal")
        self.error.delete("1.0", "end")
        self.error.insert("1.0", msg)
        self.error.configure(state="disabled")

    def hide_error(self) -> None:
        self.error.grid_remove()

    def finished(self, ok: bool, text: str) -> None:
        self.stage.configure(text=text)
        if ok:
            self.bar.set(1.0)
            self.percent.configure(text="100 %")
