"""Render: what the studio is doing right now, with a live preview of the newest frame."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar, QVBoxLayout, QWidget

from core.generation_controller import STAGES
from gui_qt import theme
from gui_qt.widgets import Card, StepTracker, button, label, rounded_pixmap
from utils.user_prefs import human_duration

SHORT = {"parse": "Script", "characters": "Characters", "voices": "Voices", "lipsync": "Lip-sync",
         "timeline": "Direction", "backgrounds": "Backgrounds", "scenes": "3D scenes", "render": "Rendering",
         "audio": "Sound mix", "subtitles": "Subtitles", "assemble": "Video", "verify": "Check"}


class RenderPage(QWidget):
    def __init__(self, state, studio):
        super().__init__()
        self.setObjectName("Page")
        self.state = state
        self.studio = studio
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 24, 32, 24)
        lay.setSpacing(16)
        head = QHBoxLayout()
        head.addWidget(label("Render", "PageTitle"))
        head.addStretch(1)
        self.cancel_btn = button("Stop", "Danger", self._cancel, "Stops now; rendered frames are kept and reused")
        self.cancel_btn.setEnabled(False)
        head.addWidget(self.cancel_btn)
        lay.addLayout(head)

        top = Card(margins=22)
        self.steps = StepTracker([(k, SHORT[k]) for k, _, _ in STAGES])
        top.lay.addWidget(self.steps)
        self.stage = label("Nothing is running. Start a cartoon from Home or Script.", "SectionTitle")
        self.stage.setStyleSheet("font-size: 20px;")
        top.lay.addWidget(self.stage)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setFormat("%p%")
        self.bar.setMinimumHeight(26)
        top.lay.addWidget(self.bar)
        info = QHBoxLayout()
        self.detail = label("", muted=True)
        self.eta = label("", muted=True)
        info.addWidget(self.detail, 1)
        info.addWidget(self.eta)
        top.lay.addLayout(info)
        lay.addWidget(top)

        row = QHBoxLayout()
        row.setSpacing(16)
        prev = Card()
        prev.lay.addWidget(label("Live preview", "SectionTitle"))
        self.preview = QLabel()
        self.preview.setMinimumSize(480, 270)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setPixmap(rounded_pixmap(None, QSize(640, 360), 12, "The newest rendered frame shows here"))
        prev.lay.addWidget(self.preview, 1)
        self.preview_caption = label("", muted=True)
        prev.lay.addWidget(self.preview_caption)
        row.addWidget(prev, 3)
        logc = Card()
        logc.lay.addWidget(label("Activity", "SectionTitle"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        self.log.setStyleSheet("font-family: monospace; font-size: 11px;")
        logc.lay.addWidget(self.log, 1)
        self.result_row = QHBoxLayout()
        self.watch_btn = button("▶ Watch video", "Primary", self._watch)
        self.folder_btn = button("Open folder", None, self._folder)
        self.result_row.addWidget(self.watch_btn)
        self.result_row.addWidget(self.folder_btn)
        self.watch_btn.hide()
        self.folder_btn.hide()
        logc.lay.addLayout(self.result_row)
        row.addWidget(logc, 2)
        lay.addLayout(row, 1)

        self._t0 = 0.0
        self._last_stage = None
        self._last_line = ""
        self._frames_dir: Path | None = None
        self._preview_timer = QTimer(self, interval=2000, timeout=self._refresh_preview)
        state.job_started.connect(self._started)
        state.job_progress.connect(self._progress)
        state.job_finished.connect(self._finished)

    # ----------------------------------------------------------------- job
    def _started(self, what: str) -> None:
        if what != "generate":
            return
        self._t0 = time.time()
        self._last_stage = None
        self.log.clear()
        self.bar.setValue(0)
        self.steps.set_stage("parse")
        self.stage.setText("Starting…")
        self.stage.setStyleSheet("font-size: 20px;")
        self.detail.setText("")
        self.eta.setText("")
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("Stop")
        self.watch_btn.hide()
        self.folder_btn.hide()
        self._frames_dir = None
        self._preview_timer.start()
        self._append(f"Started · quality {self.state.settings.quality}")

    def _progress(self, p) -> None:
        self.steps.set_stage(p.stage)
        self.bar.setValue(int(p.percent * 10))
        scene = f" · scene {p.scene} of {p.scene_count}" if p.scene else ""
        self.stage.setText(p.label + scene)
        counts = f"{p.stage_done}/{p.stage_total}  " if p.stage_total else ""
        self.detail.setText(f"{counts}{p.message}")
        elapsed = time.time() - self._t0
        if p.percent >= 3:
            left = elapsed * (100 - p.percent) / p.percent
            self.eta.setText(f"Elapsed {human_duration(int(elapsed / 60)).replace('about ', '')} · "
                             f"left {human_duration(max(1, int(left / 60)))}")
        if p.stage != self._last_stage:
            self._append(p.label)
            self._last_stage = p.stage
        elif p.message and p.message != self._last_line and p.stage != "render":
            self._append("   " + p.message)
        self._last_line = p.message
        if p.stage == "render" and p.scene:
            name = self._episode_dir()
            if name:
                self._frames_dir = name / "renders" / f"scene_{p.scene:03d}"

    def _episode_dir(self) -> Path | None:
        out = self.state.settings.output_dir
        if self.state.settings.episode_name:
            return out / self.state.settings.episode_name
        dirs = [d for d in out.iterdir() if d.is_dir()] if out.exists() else []
        return max(dirs, key=lambda d: d.stat().st_mtime) if dirs else None

    def _refresh_preview(self) -> None:
        if not self._frames_dir or not self._frames_dir.exists():
            return
        frames = sorted(self._frames_dir.glob("frame_*.jpg"))
        if len(frames) >= 2:
            newest = frames[-2]  # the last file may still be being written
            pix = QPixmap(str(newest))
            if not pix.isNull():
                w = max(320, self.preview.width() - 8)
                self.preview.setPixmap(rounded_pixmap(newest, QSize(w, int(w * 9 / 16)), 12))
                self.preview_caption.setText(f"{self._frames_dir.name.replace('_', ' ')} · {newest.stem}")

    def _finished(self, res) -> None:
        self._preview_timer.stop()
        self.cancel_btn.setEnabled(False)
        took = human_duration(max(1, int((time.time() - self._t0) / 60))).replace("about ", "")
        if res.ok:
            self.steps.set_stage("done")
            self.bar.setValue(1000)
            self.stage.setText("Your cartoon is ready! ✓")
            self.stage.setStyleSheet(f"font-size: 20px; color: {theme.OK};")
            self._append(f"Finished in {took}: {res.video}")
            self.watch_btn.show()
        else:
            cancelled = bool(res.error and "cancel" in res.error.lower())
            self.steps.set_stage(self._last_stage, failed=not cancelled)
            self.stage.setText("Stopped — press Make again to continue" if cancelled else "Something went wrong")
            self.stage.setStyleSheet(f"font-size: 20px; color: {theme.WARN if cancelled else theme.DANGER};")
            self._append("✗ " + (res.error or "Unknown error"))
        if res.episode_dir:
            self.folder_btn.show()

    def _append(self, text: str) -> None:
        self.log.appendPlainText(f"{time.strftime('%H:%M:%S')}  {text}")

    def _cancel(self) -> None:
        self.state.cancel()
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("Stopping…")

    def _watch(self) -> None:
        if self.state.episode:
            self.studio.show_episode(self.state.episode.root, play=True)

    def _folder(self) -> None:
        res = self.state.last_result
        if res and res.episode_dir:
            self.studio.open_path(res.episode_dir)
