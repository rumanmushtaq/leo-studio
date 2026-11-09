"""Script editor with highlighting (Urdu shaped right-to-left by Qt) and a live check panel."""
from __future__ import annotations

import re

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextOption
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QInputDialog, QTextEdit, QScrollArea, QSplitter,
                               QVBoxLayout, QWidget)

from core.character_manager import CharacterRegistry
from gui_qt import theme
from gui_qt.state import PROJECTS_DIR, parse_script
from gui_qt.widgets import Card, button, fmt_time, label

SCENE_RE = re.compile(r"^\s*(scene|سین|منظر)\s*\d+.*$", re.I)
VISUAL_RE = re.compile(r"^\s*(visual|بصری)\s*:?\s*$", re.I)
SPEAKER_RE = re.compile(r"^\s*([^:\n]{1,40}?)(\s*\(([^)]*)\))?\s*:\s*$")


class ScriptHighlighter(QSyntaxHighlighter):
    def __init__(self, doc):
        super().__init__(doc)

        def fmt(colour: str, bold: bool = False, size: float | None = None) -> QTextCharFormat:
            f = QTextCharFormat()
            f.setForeground(QColor(colour))
            if bold:
                f.setFontWeight(QFont.Bold)
            if size:
                f.setFontPointSize(size)
            return f

        self.scene = fmt("#7cc4ff", True, 16)
        self.visual = fmt(theme.WARN, True)
        self.speaker = fmt("#c4a5ff", True)
        self.emotion = fmt("#f9a8d4")

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        if SCENE_RE.match(text):
            self.setFormat(0, len(text), self.scene)
        elif VISUAL_RE.match(text):
            self.setFormat(0, len(text), self.visual)
        else:
            m = SPEAKER_RE.match(text)
            if m:
                self.setFormat(0, len(text), self.speaker)
                if m.group(2):
                    self.setFormat(m.start(2), len(m.group(2)), self.emotion)


class ScriptPage(QWidget):
    def __init__(self, state, studio):
        super().__init__()
        self.setObjectName("Page")
        self.state = state
        self.studio = studio
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 24, 32, 24)
        lay.setSpacing(14)

        top = QHBoxLayout()
        top.addWidget(label("Script", "PageTitle"))
        top.addStretch(1)
        top.addWidget(button("✎ AI write from idea…", None, self._ai_write,
                             "The free local AI writer turns a one-line idea into a full script"))
        top.addWidget(button("Leo sample", None, state.load_sample))
        top.addWidget(button("Open…", None, studio.open_project_dialog))
        top.addWidget(button("Save project…", None, self._save))
        lay.addLayout(top)

        split = QSplitter(Qt.Horizontal)
        split.setHandleWidth(10)
        editor_card = Card(margins=6)
        self.editor = QTextEdit()
        self.editor.setAcceptRichText(False)
        self.editor.setFont(theme.urdu_font(15))
        self.editor.setPlaceholderText("Scene 1: Village\n\nVisual:\nLeo walks in and waves.\n\nNarrator:\n"
                                       "ایک گاؤں میں ...\n\nLeo (happy):\nالسلام علیکم!")
        self.editor.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.editor.setStyleSheet("QTextEdit { border: none; background: #0d1430; padding: 14px; }")
        self.editor.document().setDocumentMargin(10)
        theme.auto_direction(self.editor)
        self.highlighter = ScriptHighlighter(self.editor.document())
        self.editor.textChanged.connect(self._edited)
        editor_card.lay.addWidget(self.editor)
        split.addWidget(editor_card)

        side_scroll = QScrollArea()
        side_scroll.setWidgetResizable(True)
        side = QWidget()
        side_scroll.setWidget(side)
        self.side = QVBoxLayout(side)
        self.side.setContentsMargins(0, 0, 0, 0)
        self.side.setSpacing(12)
        self.summary = Card()
        self.status = label("", "SectionTitle", wrap=True)
        self.summary.lay.addWidget(self.status)
        stats = QHBoxLayout()
        self.n_scenes, self.n_lines, self.n_secs = (self._stat(stats, t) for t in ("scenes", "lines", "length"))
        self.summary.lay.addLayout(stats)
        self.side.addWidget(self.summary)
        self.cast = Card()
        self.cast.lay.addWidget(label("Characters", "SectionTitle"))
        self.cast_text = label("", muted=True, wrap=True)
        self.cast.lay.addWidget(self.cast_text)
        self.side.addWidget(self.cast)
        self.scenes = Card()
        self.scenes.lay.addWidget(label("Scenes", "SectionTitle"))
        self.scene_text = label("", wrap=True)
        self.scene_text.setTextFormat(Qt.RichText)
        self.scenes.lay.addWidget(self.scene_text)
        self.side.addWidget(self.scenes)
        self.notes = Card()
        self.notes.lay.addWidget(label("Notes", "SectionTitle"))
        self.notes_text = label("", wrap=True)
        self.notes_text.setTextFormat(Qt.RichText)
        self.notes.lay.addWidget(self.notes_text)
        self.side.addWidget(self.notes)
        self.side.addStretch(1)
        split.addWidget(side_scroll)
        split.setSizes([760, 380])
        lay.addWidget(split, 1)

        bottom = QHBoxLayout()
        self.target = label("", muted=True)
        bottom.addWidget(self.target, 1)
        self.make_btn = button("✦  Make cartoon from this script", "Primary", self._make)
        bottom.addWidget(self.make_btn)
        lay.addLayout(bottom)

        self._debounce = QTimer(self, singleShot=True, timeout=self._check)
        self._loading = False
        state.script_changed.connect(self._load_text)
        state.episode_changed.connect(lambda _: self._update_target())
        state.job_started.connect(lambda _: self.make_btn.setEnabled(False))
        state.job_finished.connect(lambda _: self.make_btn.setEnabled(True))
        self._check()

    def _stat(self, row: QHBoxLayout, title: str):
        box = QVBoxLayout()
        num = label("0", "BigNumber")
        box.addWidget(num)
        box.addWidget(label(title, muted=True))
        row.addLayout(box)
        return num

    # ---------------------------------------------------------------- text
    def _load_text(self, text: str) -> None:
        if text != self.editor.toPlainText():
            self._loading = True
            self.editor.setPlainText(text)
            self._loading = False
            self._check()

    def _edited(self) -> None:
        if not self._loading:
            self.state.set_script(self.editor.toPlainText(), emit=False)
        self._debounce.start(600)

    def _check(self) -> None:
        text = self.editor.toPlainText().strip()
        self._update_target()
        if not text:
            self.status.setText("Paste or write a script, or use “AI write from idea”.")
            self.status.setStyleSheet(f"color: {theme.MUTED};")
            for n in (self.n_scenes, self.n_lines, self.n_secs):
                n.setText("–")
            self.cast_text.setText("")
            self.scene_text.setText("")
            self.notes_text.setText("")
            return
        p = parse_script(text)
        if not p.report.ok:
            self.status.setText("✗ Needs a fix before making the cartoon")
            self.status.setStyleSheet(f"color: {theme.DANGER};")
            self.notes_text.setText("<br>".join(f"<span style='color:{theme.DANGER}'>• {e}</span>"
                                                for e in p.report.errors))
            return
        lines = len(p.all_dialogue_events())
        secs = sum(s.estimated_duration for s in p.scenes)
        self.n_scenes.setText(str(len(p.scenes)))
        self.n_lines.setText(str(lines))
        self.n_secs.setText(fmt_time(secs))
        reg = CharacterRegistry()
        cast = sorted({c for s in p.scenes for c in s.characters})
        self.cast_text.setText(", ".join(reg.get_or_create(c).name for c in cast) or "none found")
        self.scene_text.setText("<br>".join(
            f"<b>{s.id}.</b> {s.title} <span style='color:{theme.MUTED}'>· {s.location.replace('_', ' ')} · "
            f"{s.estimated_duration:.0f} s</span>" for s in p.scenes))
        warn = p.report.warnings[:6]
        self.notes_text.setText("<br>".join(f"<span style='color:{theme.WARN}'>• {w}</span>" for w in warn)
                                or f"<span style='color:{theme.OK}'>Everything looks good.</span>")
        self.status.setText("✓ Ready to make" if not warn else "✓ Ready (with notes)")
        self.status.setStyleSheet(f"color: {theme.OK if not warn else theme.WARN};")

    def _update_target(self) -> None:
        ep = self.state.episode
        self.target.setText(f"Updates “{ep.name}” — unchanged scenes are reused, only changed scenes render again."
                            if ep else "Makes a new episode.")

    # ------------------------------------------------------------- actions
    def _make(self) -> None:
        ep = self.state.episode
        err = self.state.generate(self.editor.toPlainText(), ep.name if ep else None)
        if err:
            self.studio.error("Cannot start", err)
        else:
            self.state.navigate.emit("render")

    def _save(self) -> None:
        PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        name = (self.state.settings.episode_name or "my_cartoon") + ".leo.json"
        f, _ = QFileDialog.getSaveFileName(self, "Save project", str(PROJECTS_DIR / name), "Leo project (*.leo.json)")
        if f:
            if not f.endswith(".leo.json"):
                f += ".leo.json"
            self.state.save_project(f)
            self.state.toast.emit("Project saved")

    def _ai_write(self) -> None:
        idea, ok = QInputDialog.getMultiLineText(self, "AI write from idea", "Your story idea in one line:")
        if ok and idea.strip():
            lang, ok = QInputDialog.getItem(self, "Language", "Dialogue language:", ["Urdu", "English"], 0, False)
            if ok:
                self.studio.write_script(idea.strip(), "ur" if lang == "Urdu" else "en", then_generate=False)
