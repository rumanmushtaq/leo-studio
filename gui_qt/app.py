"""Main window of the Qt studio: sidebar, top bar, pages, and the story-writer flow."""
from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QButtonGroup, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QMainWindow, QMessageBox, QProgressBar, QStackedWidget, QTextBrowser, QToolButton,
                               QVBoxLayout, QWidget)

from engines.background_painter import DOWNLOAD_MB as PAINTER_MB
from engines.background_painter import BackgroundPainter
from engines.script_writer import DOWNLOAD_MB as WRITER_MB
from engines.script_writer import ScriptWriter
from gui_qt import theme
from gui_qt.icons import icon
from gui_qt.state import PROJECTS_DIR, StudioState, looks_like_script
from gui_qt.widgets import Toast, button, label
from gui_qt.workers import TaskWorker
from utils import user_prefs
from utils.config import ASSETS_DIR
from utils.notify import notify

APP_ICON = ASSETS_DIR / "icon.png"
PAGES = [("home", "Home"), ("script", "Script"), ("storyboard", "Storyboard"), ("characters", "Characters"),
         ("render", "Render"), ("publish", "Publish"), ("settings", "Settings")]


def open_path(path: Path) -> None:
    """Open a file or folder with the system's default application."""
    if platform.system() == "Windows":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif platform.system() == "Darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class ReviewDialog(QDialog):
    """Shows the AI-written story (Qt shapes Urdu right-to-left) before the long render starts."""

    def __init__(self, parent, script: str):
        super().__init__(parent)
        self.setWindowTitle("Check your story")
        self.resize(900, 700)
        self.choice = "edit"
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.addWidget(label("Check your story", "PageTitle"))
        lay.addWidget(label("The AI writer can make small word mistakes. Read it once, then make the cartoon — "
                            "or edit it first.", "PageSubtitle", wrap=True))
        view = QTextBrowser()
        view.setFont(theme.urdu_font(16))
        theme.auto_direction(view)
        view.setPlainText(script)
        lay.addWidget(view, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        for text, kind, choice in (("Write it again", None, "again"), ("Edit first", None, "edit"),
                                   ("Looks good — make the cartoon", "Primary", "make")):
            row.addWidget(button(text, kind, lambda _=False, c=choice: self._choose(c)))
        lay.addLayout(row)

    def _choose(self, c: str) -> None:
        self.choice = c
        self.accept()


class StudioWindow(QMainWindow):
    def __init__(self, state: StudioState | None = None):
        super().__init__()
        self.state = state or StudioState()
        self.setWindowTitle("Leo 3D AI Cartoon Studio")
        if APP_ICON.exists():
            self.setWindowIcon(QIcon(str(APP_ICON)))
        self.resize(1360, 880)
        self.setMinimumSize(1100, 720)
        self._task: TaskWorker | None = None

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(self._sidebar())
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        right.addWidget(self._topbar())
        self.stack = QStackedWidget()
        right.addWidget(self.stack, 1)
        h.addLayout(right, 1)
        self.toast = Toast(root)

        from gui_qt.pages.characters import CharactersPage
        from gui_qt.pages.home import HomePage
        from gui_qt.pages.publish import PublishPage
        from gui_qt.pages.render import RenderPage
        from gui_qt.pages.script import ScriptPage
        from gui_qt.pages.settings import SettingsPage
        from gui_qt.pages.storyboard import StoryboardPage

        classes = {"home": HomePage, "script": ScriptPage, "storyboard": StoryboardPage,
                   "characters": CharactersPage, "render": RenderPage, "publish": PublishPage,
                   "settings": SettingsPage}
        self.pages = {}
        for key, _ in PAGES:
            page = classes[key](self.state, self)
            self.pages[key] = page
            self.stack.addWidget(page)

        s = self.state
        s.navigate.connect(self.go)
        s.toast.connect(lambda m: self.toast.show_message(m))
        s.job_started.connect(self._job_started)
        s.job_progress.connect(self._job_progress)
        s.job_finished.connect(self._job_finished)
        s.episode_changed.connect(self._episode_changed)
        self._episode_changed(s.episode)
        for i, (key, _) in enumerate(PAGES[:7], start=1):
            QShortcut(QKeySequence(f"Ctrl+{i}"), self, activated=lambda k=key: self.go(k))
        self.go(user_prefs.load().get("last_page", "home") if user_prefs.load().get("last_page") != "render"
                else "home")
        if s.hw.warnings:
            QTimer.singleShot(600, lambda: self.toast.show_message("⚠ " + s.hw.warnings[0], 8000))

    # ----------------------------------------------------------------- chrome
    def _sidebar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("Sidebar")
        bar.setFixedWidth(92)
        lay = QVBoxLayout(bar)
        lay.setContentsMargins(8, 16, 8, 16)
        lay.setSpacing(6)
        logo = QLabel()
        if APP_ICON.exists():
            logo.setPixmap(QIcon(str(APP_ICON)).pixmap(46, 46))
        logo.setAlignment(Qt.AlignCenter)
        lay.addWidget(logo)
        name = label("LEO", "Logo")
        name.setAlignment(Qt.AlignCenter)
        lay.addWidget(name)
        lay.addSpacing(14)
        self.nav = QButtonGroup(self)
        self.nav_buttons = {}
        for key, title in PAGES:
            b = QToolButton()
            b.setObjectName("NavButton")
            b.setText(title)
            b.setIcon(icon(key))
            b.setIconSize(QSize(24, 24))
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedSize(76, 62)
            b.clicked.connect(lambda _=False, k=key: self.go(k))
            self.nav.addButton(b)
            self.nav_buttons[key] = b
            if key == "settings":
                lay.addStretch(1)
            lay.addWidget(b, 0, Qt.AlignHCenter)
        return bar

    def _topbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(64)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(24, 8, 20, 8)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.project = label("Leo 3D AI Cartoon Studio", "ProjectName")
        self.status = label("Ready", muted=True)
        col.addWidget(self.project)
        col.addWidget(self.status)
        lay.addLayout(col, 1)
        self.mini = QProgressBar()
        self.mini.setRange(0, 1000)
        self.mini.setFixedWidth(220)
        self.mini.setTextVisible(False)
        self.mini.setFixedHeight(10)
        self.mini.hide()
        lay.addWidget(self.mini)
        self.top_btn = button("✦  New cartoon", "Primary", self._top_action)
        lay.addWidget(self.top_btn)
        return bar

    def go(self, key: str) -> None:
        self.stack.setCurrentWidget(self.pages[key])
        self.nav_buttons[key].setChecked(True)
        if key == "home":
            self.pages["home"].focus_box()
        user_prefs.save(last_page=key)

    def _top_action(self) -> None:
        if self.state.busy:
            self.go("render")
        else:
            self.go("home")
            self.pages["home"].focus_box()

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        if self.toast.isVisible():
            self.toast.show_message(self.toast.text())

    # ------------------------------------------------------------ messages
    def error(self, title: str, text: str) -> None:
        QMessageBox.warning(self, title, text)

    def open_path(self, path: Path) -> None:
        try:
            open_path(Path(path))
        except OSError as exc:
            self.error("Cannot open", str(exc))

    # ------------------------------------------------------------ episodes
    def open_project_dialog(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Open project or script", str(PROJECTS_DIR),
                                           "Script or project (*.txt *.leo.json);;All files (*)")
        if f:
            self.state.open_file(Path(f))
            self.go("script")

    def show_episode(self, root: Path, play: bool = False) -> None:
        self.state.open_episode(Path(root))
        self.go("storyboard")
        if play:
            self.pages["storyboard"].player.seek_to(0.0)

    def edit_episode(self, root: Path) -> None:
        self.state.open_episode(Path(root))
        self.go("script")

    def continue_episode(self, root: Path) -> None:
        self.state.open_episode(Path(root))
        ep = self.state.episode
        if not ep or not ep.script:
            self.error("Cannot continue", "No saved script was found for this episode.")
            return
        err = self.state.generate(ep.script, ep.name)
        if err:
            self.error("Cannot start", err)
        else:
            self.go("render")

    def _episode_changed(self, ep) -> None:
        self.project.setText(ep.name.replace("_", " ").title() if ep else "Leo 3D AI Cartoon Studio")

    # ----------------------------------------------------------- generation
    def make_cartoon(self, text: str, language: str, new_episode: bool = True) -> None:
        if self.state.busy:
            self.toast.show_message("Please wait — another job is running.")
            return
        if new_episode:
            self.state.open_episode(None)
        if looks_like_script(text):
            self._start(text)
        else:
            self.write_script(text, language, then_generate=True)

    def _start(self, script: str) -> None:
        ep = self.state.episode
        err = self.state.generate(script, ep.name if ep else None)
        if err:
            self.error("Cannot start", err)
        else:
            self.go("render")

    def _consent(self, need_writer: bool) -> tuple[bool, bool]:
        """Ask once to download the free AI tools; returns (writer ok, painter wanted)."""
        prefs = user_prefs.load()
        need_painter = (BackgroundPainter.available() and not BackgroundPainter.is_installed()
                        and not prefs.get("declined_backgrounds"))
        if not need_writer and not need_painter:
            return True, False
        items = []
        if need_writer:
            items.append(f"• AI story writer (turns your idea into a script): {WRITER_MB / 1000:.1f} GB")
        if need_painter:
            items.append(f"• AI background painter (beautiful scenery): {PAINTER_MB / 1000:.1f} GB")
        ok = QMessageBox.question(self, "Free AI tools",
                                  "These free AI tools run on this computer (no internet needed afterwards):\n\n"
                                  + "\n".join(items) + "\n\nOne-time download. Download now?") == QMessageBox.Yes
        if not ok and need_painter:
            user_prefs.save(declined_backgrounds=True)
        return (ok or not need_writer), (ok and need_painter)

    def write_script(self, idea: str, language: str, then_generate: bool) -> None:
        writer = ScriptWriter()
        writer_ok, get_painter = self._consent(not writer.is_installed())
        if not writer_ok:
            self.toast.show_message("Paste a full script instead, or allow the download to use story ideas.", 6000)
            return

        def job(progress):
            if get_painter:
                BackgroundPainter.install(progress)
            if not writer.is_installed():
                writer.install(progress)
            return writer.write(idea, language, progress=progress)

        self.state.busy_with = "write"
        self.state.job_started.emit("write")
        self._task = TaskWorker(job)
        self._task.progress.connect(lambda f, m: (self.status.setText(m), self.mini.setValue(int(f * 1000))))
        self._task.done.connect(lambda script: self._written(script, idea, language, then_generate))
        self._task.failed.connect(self._write_failed)
        self._task.start()

    def _write_done(self) -> None:
        self.state.busy_with = None
        self.mini.hide()
        self.top_btn.setText("✦  New cartoon")
        self.status.setText("Ready")

    def _write_failed(self, err: str) -> None:
        self._write_done()
        self.error("AI writer problem", err)

    def _written(self, script: str, idea: str, language: str, then_generate: bool) -> None:
        self._write_done()
        self.state.set_script(script)
        if not then_generate:
            self.go("script")
            self.toast.show_message("Story written — check it and press Make")
            return
        dlg = ReviewDialog(self, script)
        dlg.exec()
        if dlg.choice == "make":
            self._start(script)
        elif dlg.choice == "again":
            self.write_script(idea, language, then_generate=True)
        else:
            self.go("script")

    # ------------------------------------------------------------ job chrome
    def _job_started(self, what: str) -> None:
        self.mini.setValue(0)
        self.mini.show()
        self.top_btn.setText("View progress")
        self.status.setText("Writing your story…" if what == "write" else "Making your cartoon…")

    def _job_progress(self, p) -> None:
        self.mini.setValue(int(p.percent * 10))
        scene = f" · scene {p.scene}/{p.scene_count}" if p.scene else ""
        self.status.setText(f"{p.label}{scene} · {p.percent:.0f}%")

    def _job_finished(self, res) -> None:
        self.mini.hide()
        self.top_btn.setText("✦  New cartoon")
        msg = "Your cartoon is ready!" if res.ok else "Stopped: " + (res.error or "error")[:120]
        self.status.setText(msg)
        notify("Leo 3D AI Cartoon Studio", msg, str(APP_ICON))
        QApplication.alert(self, 0)
        if res.ok and self.state.episode:
            self.toast.show_message("✓ " + msg, 6000)


def run_app() -> int:
    QApplication.setApplicationName("leo3dstudio")
    QApplication.setApplicationDisplayName("Leo 3D AI Cartoon Studio")
    QApplication.setDesktopFileName("leo-3d-ai-cartoon-studio")
    app = QApplication.instance() or QApplication(sys.argv)
    theme.apply(app)
    splash = None
    if APP_ICON.exists():
        from PySide6.QtGui import QColor, QPainter, QPixmap
        from PySide6.QtWidgets import QSplashScreen

        pix = QPixmap(420, 240)
        pix.fill(QColor(theme.PANEL))
        p = QPainter(pix)
        p.drawPixmap(170, 40, QIcon(str(APP_ICON)).pixmap(80, 80))
        p.end()
        splash = QSplashScreen(pix)
        splash.showMessage("Leo 3D AI Cartoon Studio\nStarting…", Qt.AlignHCenter | Qt.AlignBottom, QColor(theme.TEXT))
        splash.show()
        app.processEvents()
    win = StudioWindow()
    win.show()
    if splash:
        splash.finish(win)
    return app.exec()
