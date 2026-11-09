"""Reusable widgets: cards, chips, thumbnail cards, step tracker, toast, flow layout, video player."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLayout, QPushButton, QSizePolicy, QSlider,
                               QStyle, QVBoxLayout, QWidget)

from gui_qt import theme


def label(text: str = "", name: str | None = None, wrap: bool = False, muted: bool = False) -> QLabel:
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    if muted:
        lab.setProperty("muted", True)
    lab.setWordWrap(wrap)
    return lab


def button(text: str, kind: str | None = None, slot=None, tip: str | None = None) -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setObjectName(kind)
    b.setCursor(Qt.PointingHandCursor)
    if slot:
        b.clicked.connect(slot)
    if tip:
        b.setToolTip(tip)
    return b


class Card(QFrame):
    def __init__(self, parent=None, name: str = "Card", margins: int = 18, spacing: int = 10):
        super().__init__(parent)
        self.setObjectName(name)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(margins, margins, margins, margins)
        self.lay.setSpacing(spacing)


def rounded_pixmap(path: Path | str | None, size: QSize, radius: int = 12, placeholder: str = "") -> QPixmap:
    """Image scaled to fill ``size`` (centre crop) with rounded corners; a gradient tile when missing."""
    out = QPixmap(size)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    clip = QPainterPath()
    clip.addRoundedRect(0, 0, size.width(), size.height(), radius, radius)
    p.setClipPath(clip)
    src = QPixmap(str(path)) if path and Path(path).exists() else QPixmap()
    if not src.isNull():
        scaled = src.scaled(size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        p.drawPixmap(QPoint((size.width() - scaled.width()) // 2, (size.height() - scaled.height()) // 2), scaled)
    else:
        from PySide6.QtGui import QLinearGradient

        g = QLinearGradient(0, 0, size.width(), size.height())
        g.setColorAt(0, QColor("#18224a"))
        g.setColorAt(1, QColor("#221c4a"))
        p.fillRect(0, 0, size.width(), size.height(), g)
        p.setPen(QColor(theme.MUTED))
        f = QFont(theme.UI_FAMILY, 10)
        p.setFont(f)
        p.drawText(QRect(0, 0, size.width(), size.height()), Qt.AlignCenter | Qt.TextWordWrap, placeholder)
    p.end()
    return out


class ThumbCard(QFrame):
    """Picture + title + subtitle; clickable; optional action buttons below."""

    clicked = Signal()

    def __init__(self, title: str, subtitle: str = "", image: Path | None = None, size: QSize = QSize(260, 146),
                 placeholder: str = "", badge: str = ""):
        super().__init__()
        self.setObjectName("ThumbCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedWidth(size.width() + 20)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)
        self.pic = QLabel()
        self.pic.setFixedSize(size)
        self._size = size
        self.set_image(image, placeholder)
        lay.addWidget(self.pic)
        if badge:
            b = QLabel(badge, self.pic)
            b.setStyleSheet(f"background: rgba(10,16,32,0.8); border-radius: 8px; padding: 3px 8px; "
                            f"font-size: 11px; font-weight: 700; color: {theme.TEXT};")
            b.move(8, 8)
        self.title = label(title, "SectionTitle")
        self.title.setWordWrap(True)
        lay.addWidget(self.title)
        self.subtitle = label(subtitle, muted=True, wrap=True)
        if subtitle:
            lay.addWidget(self.subtitle)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(6)
        lay.addLayout(self.actions)

    def set_image(self, image: Path | None, placeholder: str = "") -> None:
        self.pic.setPixmap(rounded_pixmap(image, self._size, 10, placeholder))

    def set_selected(self, on: bool) -> None:
        self.setProperty("selected", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802 (Qt API)
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(e)


class FlowLayout(QLayout):
    """Wraps child widgets onto new rows (gallery grids that adapt to the window width)."""

    def __init__(self, parent=None, spacing: int = 14):
        super().__init__(parent)
        self._items = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, i):  # noqa: N802
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):  # noqa: N802
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientations(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        return s

    def clear(self) -> None:
        while self._items:
            it = self._items.pop()
            if it.widget():
                it.widget().deleteLater()

    def _do_layout(self, rect: QRect, test: bool) -> int:
        x, y, line_h, sp = rect.x(), rect.y(), 0, self.spacing()
        for it in self._items:
            w = it.sizeHint()
            if x + w.width() > rect.right() + 1 and line_h > 0:
                x, y, line_h = rect.x(), y + line_h + sp, 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), w))
            x += w.width() + sp
            line_h = max(line_h, w.height())
        return y + line_h - rect.y()


class StepTracker(QWidget):
    """Row of numbered dots for the generation stages."""

    def __init__(self, stages: list[tuple[str, str]]):
        super().__init__()
        self.stages = stages
        self.current = -1
        self.failed = False
        self.setMinimumHeight(70)

    def set_stage(self, key: str | None, failed: bool = False) -> None:
        keys = [k for k, _ in self.stages]
        self.current = keys.index(key) if key in keys else (len(keys) if key == "done" else -1)
        self.failed = failed
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        n = len(self.stages)
        w = self.width()
        step = (w - 40) / max(1, n - 1)
        y = 18
        p.setPen(QColor(theme.BORDER))
        p.drawLine(20, y, int(w - 20), y)
        small = QFont(theme.UI_FAMILY, 8)
        for i, (_, name) in enumerate(self.stages):
            x = int(20 + i * step)
            if i < self.current:
                col = QColor(theme.OK)
            elif i == self.current:
                col = QColor(theme.DANGER if self.failed else theme.ACCENT)
            else:
                col = QColor("#2a3766")
            p.setBrush(col)
            p.setPen(Qt.NoPen)
            r = 9 if i == self.current else 7
            p.drawEllipse(QPoint(x, y), r, r)
            p.setPen(QColor(theme.TEXT if i == self.current else theme.MUTED))
            p.setFont(small)
            p.drawText(QRect(x - 45, y + 14, 90, 36), Qt.AlignHCenter | Qt.TextWordWrap, name)
        p.end()


class Toast(QLabel):
    """Short message that fades away at the bottom of the window."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("Toast")
        self.hide()
        self._timer = QTimer(self, singleShot=True, timeout=self.hide)

    def show_message(self, text: str, ms: int = 3500) -> None:
        self.setText(text)
        self.adjustSize()
        par = self.parentWidget()
        self.move(par.width() - self.width() - 28, par.height() - self.height() - 28)
        self.raise_()
        self.show()
        self._timer.start(ms)


def hline() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet(f"color: {theme.BORDER}; background: {theme.BORDER}; max-height: 1px;")
    return f


def section(title: str, subtitle: str = "") -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(2)
    lay.addWidget(label(title, "PageTitle"))
    if subtitle:
        lay.addWidget(label(subtitle, "PageSubtitle", wrap=True))
    return w


def fmt_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:d}:{seconds % 60:02d}"


class SeekBar(QSlider):
    """Slider that jumps to the clicked position and draws scene markers."""

    def __init__(self):
        super().__init__(Qt.Horizontal)
        self.markers: list[float] = []  # fractions 0..1

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.LeftButton and self.width() > 0:
            v = QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), int(e.position().x()), self.width())
            self.setValue(v)
            self.sliderMoved.emit(v)
        super().mousePressEvent(e)

    def paintEvent(self, e) -> None:  # noqa: N802
        super().paintEvent(e)
        if not self.markers:
            return
        p = QPainter(self)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.WARN))
        for f in self.markers:
            x = int(8 + f * (self.width() - 16))
            p.drawRoundedRect(x - 1, self.height() // 2 - 7, 3, 14, 1, 1)
        p.end()


class VideoPlayer(QFrame):
    """Qt Multimedia player: video, play/pause, seek bar with scene markers, time."""

    position_changed = Signal(float)  # seconds

    def __init__(self):
        super().__init__()
        self.setObjectName("Card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)
        self.player = None
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
            from PySide6.QtMultimediaWidgets import QVideoWidget

            self.video = QVideoWidget()
            self.video.setMinimumHeight(240)
            self.video.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.video.setStyleSheet("background: black; border-radius: 10px;")
            self.player = QMediaPlayer(self)
            self.audio = QAudioOutput(self)
            self.player.setAudioOutput(self.audio)
            self.player.setVideoOutput(self.video)
            self.player.positionChanged.connect(self._on_pos)
            self.player.durationChanged.connect(self._on_duration)
            self.player.playbackStateChanged.connect(self._on_state)
            from PySide6.QtWidgets import QStackedWidget

            self.screen = QStackedWidget()
            self.poster = QLabel()
            self.poster.setAlignment(Qt.AlignCenter)
            self.poster.setMinimumHeight(240)
            self.poster.setStyleSheet("background: #05080f; border-radius: 10px;")
            self.poster.setCursor(Qt.PointingHandCursor)
            self.poster.mousePressEvent = lambda _e: self.toggle()
            self.screen.addWidget(self.poster)
            self.screen.addWidget(self.video)
            lay.addWidget(self.screen, 1)
        except ImportError:  # Qt Multimedia missing: still offer the system player
            self.video = label("Video preview is not available on this computer.\nUse 'Open in player'.",
                               muted=True)
            self.video.setAlignment(Qt.AlignCenter)
            lay.addWidget(self.video, 1)
        row = QHBoxLayout()
        self.play_btn = button("▶", slot=self.toggle)
        self.play_btn.setFixedWidth(48)
        self.seek = SeekBar()
        self.seek.sliderMoved.connect(lambda v: self.player and self.player.setPosition(v))
        self.time = label("0:00 / 0:00", muted=True)
        self.time.setMinimumWidth(96)
        row.addWidget(self.play_btn)
        row.addWidget(self.seek, 1)
        row.addWidget(self.time)
        lay.addLayout(row)
        self._duration = 0
        self._path: Path | None = None
        self._poster: Path | None = None

    def load(self, path: Path | None, markers: list[float] | None = None, poster: Path | None = None) -> None:
        self._path = path
        self._poster = poster
        self.seek.markers = markers or []
        self.seek.update()
        if self.player is None:
            return
        self.player.stop()
        self._show_poster()
        self.player.setSource(QUrl.fromLocalFile(str(path)) if path else QUrl())

    def toggle(self) -> None:
        if self.player is None:
            return
        from PySide6.QtMultimedia import QMediaPlayer

        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def seek_to(self, seconds: float, play: bool = True) -> None:
        if self.player is None:
            return
        self.player.setPosition(int(seconds * 1000))
        if play:
            self.player.play()

    def stop(self) -> None:
        if self.player is not None:
            self.player.pause()

    def _show_poster(self) -> None:
        size = self.screen.size() if self.screen.width() > 50 else QSize(960, 400)
        h = size.height()
        w = min(size.width(), int(h * 16 / 9))
        pix = rounded_pixmap(self._poster, QSize(w, h), 10, "" if self._poster else "No video yet")
        if self._path:
            p = QPainter(pix)
            p.setRenderHint(QPainter.Antialiasing)
            p.setBrush(QColor(10, 14, 30, 190))
            p.setPen(Qt.NoPen)
            c = QPoint(w // 2, h // 2)
            p.drawEllipse(c, 42, 42)
            p.setBrush(QColor("#ffffff"))
            from PySide6.QtGui import QPolygon

            p.drawPolygon(QPolygon([QPoint(c.x() - 13, c.y() - 20), QPoint(c.x() - 13, c.y() + 20),
                                    QPoint(c.x() + 22, c.y())]))
            p.end()
        self.poster.setPixmap(pix)
        self.screen.setCurrentWidget(self.poster)

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        if self.player is not None and self.screen.currentWidget() is self.poster:
            self._show_poster()

    def _on_pos(self, ms: int) -> None:
        if not self.seek.isSliderDown():
            self.seek.setValue(ms)
        self.time.setText(f"{fmt_time(ms / 1000)} / {fmt_time(self._duration / 1000)}")
        self.position_changed.emit(ms / 1000)

    def _on_duration(self, ms: int) -> None:
        self._duration = ms
        self.seek.setRange(0, ms)

    def _on_state(self, state) -> None:
        from PySide6.QtMultimedia import QMediaPlayer

        self.play_btn.setText("❚❚" if state == QMediaPlayer.PlayingState else "▶")
        if state == QMediaPlayer.PlayingState:
            self.screen.setCurrentWidget(self.video)


class Segmented(QWidget):
    """Pill buttons where exactly one is chosen (like a segmented control)."""

    changed = Signal(str)

    def __init__(self, options: list[str], current: str | None = None):
        super().__init__()
        from PySide6.QtWidgets import QButtonGroup

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.group = QButtonGroup(self)
        self.buttons: dict[str, QPushButton] = {}
        for opt in options:
            b = button(opt, "Chip")
            b.setCheckable(True)
            self.group.addButton(b)
            self.buttons[opt] = b
            lay.addWidget(b)
            b.toggled.connect(lambda on, o=opt: on and self.changed.emit(o))
        lay.addStretch(1)
        self.set(current or options[0])

    def set(self, value: str) -> None:
        if value in self.buttons:
            self.buttons[value].setChecked(True)

    def value(self) -> str:
        b = self.group.checkedButton()
        return b.text() if b else ""
