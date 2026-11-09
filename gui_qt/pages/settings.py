"""Settings: voices, music, output folder, render engine, free AI tools, this computer."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QLineEdit,
                               QScrollArea, QVBoxLayout, QWidget)

from engines.background_painter import DOWNLOAD_MB as PAINTER_MB
from engines.background_painter import BackgroundPainter
from engines.script_writer import DOWNLOAD_MB as WRITER_MB
from engines.script_writer import ScriptWriter
from gui_qt import theme
from gui_qt.widgets import Card, button, label
from gui_qt.workers import TaskWorker
from models.model_manager import model_status

VOICES = {"auto": "Automatic (best available)", "mms": "MMS natural voice (non-commercial)",
          "espeak": "eSpeak (robotic, commercial OK)", "manual": "My own recordings"}
QUALITIES = {"preview": "Quick (640×360 render, upscaled)", "standard": "Best (1280×720)",
             "high": "Highest (slow)"}


class SettingsPage(QWidget):
    def __init__(self, state, studio):
        super().__init__()
        self.setObjectName("Page")
        self.state = state
        self.studio = studio
        self._task = None
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(32, 24, 32, 32)
        lay.setSpacing(16)
        lay.addWidget(label("Settings", "PageTitle"))
        grid = QGridLayout()
        grid.setSpacing(16)
        s = state.settings

        video = Card()
        video.lay.addWidget(label("Video", "SectionTitle"))
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.quality = QComboBox()
        for k, v in QUALITIES.items():
            self.quality.addItem(v, k)
        form.addRow("Quality", self.quality)
        out_row = QHBoxLayout()
        self.output = QLineEdit(str(s.output_dir))
        out_row.addWidget(self.output, 1)
        out_row.addWidget(button("Browse…", None, self._pick_output))
        form.addRow("Save videos in", out_row)
        self.music = QCheckBox("Background music (original, generated)")
        form.addRow("", self.music)
        self.backgrounds = QCheckBox("AI-painted backgrounds when the painter is installed")
        form.addRow("", self.backgrounds)
        video.lay.addLayout(form)
        grid.addWidget(video, 0, 0)

        voice = Card()
        voice.lay.addWidget(label("Voices", "SectionTitle"))
        vform = QFormLayout()
        self.voice = QComboBox()
        for k, v in VOICES.items():
            self.voice.addItem(v, k)
        vform.addRow("Voice engine", self.voice)
        mrow = QHBoxLayout()
        self.manual = QLineEdit(str(s.manual_audio_dir or ""))
        self.manual.setPlaceholderText("Folder with s01_e001.wav or 001.wav files")
        mrow.addWidget(self.manual, 1)
        mrow.addWidget(button("Browse…", None, self._pick_manual))
        vform.addRow("My recordings", mrow)
        voice.lay.addLayout(vform)
        voice.lay.addWidget(label("MMS voices are free for non-commercial use only. For a monetised channel "
                                  "use eSpeak or your own recordings.", muted=True, wrap=True))
        grid.addWidget(voice, 0, 1)

        engine = Card()
        engine.lay.addWidget(label("Render engine", "SectionTitle"))
        eform = QFormLayout()
        self.engine = QComboBox()
        self.engine.addItem("Blender 3D on this computer", "blender")
        self.engine.addItem("AI video on a GPU server (ComfyUI)", "ai")
        eform.addRow("Engine", self.engine)
        crow = QHBoxLayout()
        self.comfy = QLineEdit(s.comfy_url)
        crow.addWidget(self.comfy, 1)
        crow.addWidget(button("Test", None, self._test_comfy))
        eform.addRow("ComfyUI address", crow)
        engine.lay.addLayout(eform)
        self.comfy_status = label("AI video needs a PC with an NVIDIA GPU running ComfyUI.", muted=True, wrap=True)
        engine.lay.addWidget(self.comfy_status)
        grid.addWidget(engine, 1, 0)

        tools = Card()
        tools.lay.addWidget(label("Free AI tools (run on this computer)", "SectionTitle"))
        self.writer_status = label("", wrap=True)
        self.painter_status = label("", wrap=True)
        trow1 = QHBoxLayout()
        trow1.addWidget(self.writer_status, 1)
        self.writer_btn = button(f"Download ({WRITER_MB / 1000:.1f} GB)", None, self._get_writer)
        trow1.addWidget(self.writer_btn)
        trow2 = QHBoxLayout()
        trow2.addWidget(self.painter_status, 1)
        self.painter_btn = button(f"Download ({PAINTER_MB / 1000:.1f} GB)", None, self._get_painter)
        trow2.addWidget(self.painter_btn)
        tools.lay.addLayout(trow1)
        tools.lay.addLayout(trow2)
        self.models = label("", muted=True, wrap=True)
        tools.lay.addWidget(self.models)
        grid.addWidget(tools, 1, 1)

        hw = Card()
        hw.lay.addWidget(label("This computer", "SectionTitle"))
        hw.lay.addWidget(label("\n".join(state.hw.summary_lines()), muted=True, wrap=True))
        for w in state.hw.warnings:
            hw.lay.addWidget(label("⚠ " + w, wrap=True))
        grid.addWidget(hw, 2, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        save = QHBoxLayout()
        save.addStretch(1)
        save.addWidget(button("Save settings", "Primary", self._save))
        lay.addLayout(save)
        lay.addStretch(1)
        self.load()

    def load(self) -> None:
        s = self.state.settings
        self.quality.setCurrentIndex(max(0, self.quality.findData(s.quality)))
        self.output.setText(str(s.output_dir))
        self.music.setChecked(s.music)
        self.backgrounds.setChecked(s.ai_backgrounds)
        self.voice.setCurrentIndex(max(0, self.voice.findData(s.voice_backend)))
        self.engine.setCurrentIndex(max(0, self.engine.findData(s.render_engine)))
        self.comfy.setText(s.comfy_url)
        self._tool_status()

    def _tool_status(self) -> None:
        w_ok = ScriptWriter().is_installed()
        p_ok = BackgroundPainter.available() and BackgroundPainter.is_installed()
        ok, no = f"color: {theme.OK};", f"color: {theme.MUTED};"
        self.writer_status.setText("✓ Story writer ready (Qwen3-4B, llama.cpp)" if w_ok else
                                   "Story writer — turns a one-line idea into a script")
        self.writer_status.setStyleSheet(ok if w_ok else no)
        self.writer_btn.setVisible(not w_ok)
        self.painter_status.setText("✓ Background painter ready (LCM Dreamshaper, OpenVINO)" if p_ok else
                                    "Background painter — paints scenery for each place")
        self.painter_status.setStyleSheet(ok if p_ok else no)
        self.painter_btn.setVisible(not p_ok and BackgroundPainter.available())
        self.models.setText("\n".join(
            f"• {m['purpose']}: {'ready' if m['downloaded'] else 'not downloaded'} ({m['license']})"
            for m in model_status() if m["integrated"]))

    def _save(self) -> None:
        s = self.state.settings
        s.quality = self.quality.currentData()
        s.output_dir = Path(self.output.text().strip() or s.output_dir)
        s.music = self.music.isChecked()
        s.ai_backgrounds = self.backgrounds.isChecked()
        s.voice_backend = self.voice.currentData()
        s.manual_audio_dir = Path(self.manual.text()) if self.manual.text().strip() else None
        s.render_engine = self.engine.currentData()
        s.comfy_url = self.comfy.text().strip() or s.comfy_url
        self.state.save_settings()
        self.state.toast.emit("Settings saved")

    def _pick_output(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Save videos in", self.output.text())
        if d:
            self.output.setText(d)

    def _pick_manual(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Folder with my recordings", self.manual.text())
        if d:
            self.manual.setText(d)

    def _test_comfy(self) -> None:
        from engines.ai_video.comfy_client import ComfyClient, ComfyError

        self.comfy_status.setText("Connecting…")
        self.comfy_status.repaint()
        try:
            self.comfy_status.setText("✓ " + ComfyClient(self.comfy.text().strip(), timeout=8).describe())
            self.comfy_status.setStyleSheet(f"color: {theme.OK};")
        except ComfyError as exc:
            self.comfy_status.setText("✗ " + str(exc))
            self.comfy_status.setStyleSheet(f"color: {theme.DANGER};")

    def _download(self, fn, status) -> None:
        if self._task and self._task.isRunning():
            return
        self._task = TaskWorker(lambda progress: fn(progress))
        self._task.progress.connect(lambda f, m: status.setText(m))
        self._task.done.connect(lambda _: (self._tool_status(), self.state.toast.emit("Download finished")))
        self._task.failed.connect(lambda e: self.studio.error("Download failed", e))
        self._task.start()

    def _get_writer(self) -> None:
        self._download(ScriptWriter().install, self.writer_status)

    def _get_painter(self) -> None:
        self._download(BackgroundPainter.install, self.painter_status)
