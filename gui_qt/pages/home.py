"""Home: make a new cartoon from an idea or script, and the gallery of past episodes."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QTextEdit, QScrollArea, QVBoxLayout, QWidget

from gui_qt import theme
from gui_qt.episodes import find_episodes, make_thumbnail
from gui_qt.state import looks_like_script, parse_script
from gui_qt.widgets import Card, FlowLayout, Segmented, ThumbCard, button, fmt_time, label
from utils.user_prefs import estimate_minutes, human_duration

EXAMPLES = ["Leo saves a lost goat in the village", "Bilal's motorcycle breaks down and Ustad Akram helps",
            "The bullies learn to share at the park", "لیو بچوں کو صفائی کا سبق سکھاتا ہے"]


class HomePage(QWidget):
    def __init__(self, state, studio):
        super().__init__()
        self.setObjectName("Page")
        self.state = state
        self.studio = studio  # main window: writer flow, dialogs
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(32, 28, 32, 32)
        lay.setSpacing(22)

        hero = Card(name="Hero", margins=28, spacing=12)
        hero.lay.addWidget(label("Make a new cartoon", "PageTitle"))
        hero.lay.addWidget(label("Write your story idea in one line — the free AI writer turns it into a script. "
                                 "Or paste a full script.", "PageSubtitle", wrap=True))
        self.box = QTextEdit()
        self.box.setAcceptRichText(False)
        self.box.setPlaceholderText("Example: Leo helps a lost goat find its way home in the village")
        self.box.setFont(theme.urdu_font(15))
        self.box.setFixedHeight(110)
        theme.auto_direction(self.box)
        self.box.textChanged.connect(lambda: self._debounce.start(400))
        hero.lay.addWidget(self.box)
        chips = QHBoxLayout()
        chips.addWidget(label("Try:", muted=True))
        for idea in EXAMPLES:
            chips.addWidget(button(idea, "Chip", lambda _=False, i=idea: self.box.setPlainText(i)))
        chips.addStretch(1)
        hero.lay.addLayout(chips)
        opts = QGridLayout()
        opts.setHorizontalSpacing(14)
        opts.addWidget(label("Language", muted=True), 0, 0)
        self.lang = Segmented(["Urdu", "English"], "Urdu")
        opts.addWidget(self.lang, 0, 1)
        opts.addWidget(label("Speed", muted=True), 0, 2)
        self.speed = Segmented(["Quick", "Best quality"],
                               "Quick" if state.settings.quality == "preview" else "Best quality")
        self.speed.changed.connect(lambda _: self._update_estimate())
        opts.addWidget(self.speed, 0, 3)
        opts.setColumnStretch(4, 1)
        hero.lay.addLayout(opts)
        row = QHBoxLayout()
        self.estimate = label("", muted=True, wrap=True)
        row.addWidget(self.estimate, 1)
        self.make_btn = button("✦  Make my cartoon", "Primary", self._make)
        self.make_btn.setProperty("class", "Big")
        self.make_btn.setMinimumHeight(52)
        self.make_btn.setStyleSheet("font-size: 18px; padding: 12px 30px; border-radius: 14px;")
        row.addWidget(self.make_btn)
        hero.lay.addLayout(row)
        lay.addWidget(hero)

        head = QHBoxLayout()
        head.addWidget(label("Your cartoons", "PageTitle"))
        head.addStretch(1)
        head.addWidget(button("Open project…", None, studio.open_project_dialog))
        head.addWidget(button("Refresh", None, self.refresh))
        lay.addLayout(head)
        self.gallery_host = QWidget()
        self.gallery = FlowLayout(self.gallery_host, spacing=16)
        lay.addWidget(self.gallery_host)
        self.empty = label("No cartoons yet. Your finished videos appear here.", muted=True)
        lay.addWidget(self.empty)
        lay.addStretch(1)

        self._debounce = QTimer(self, singleShot=True, timeout=self._update_estimate)
        state.job_started.connect(lambda _: self._set_busy(True))
        state.job_finished.connect(lambda _: (self._set_busy(False), self.refresh()))
        self._update_estimate()
        QTimer.singleShot(0, self.refresh)

    # ---------------------------------------------------------------- gallery
    def refresh(self) -> None:
        self.gallery.clear()
        eps = find_episodes(self.state.settings.output_dir)
        self.empty.setVisible(not eps)
        for ep in eps:
            done = sum(s.frames_done for s in ep.scenes)
            total = sum(s.frame_count for s in ep.scenes) or 1
            status = (f"{fmt_time(ep.duration)} · {len(ep.scenes)} scenes" if ep.video
                      else f"Unfinished · {100 * done // total}% rendered")
            card = ThumbCard(ep.name.replace("_", " ").title(), f"{status}\n{ep.modified:%d %b %Y, %H:%M}",
                             make_thumbnail(ep), QSize(272, 153), "No preview yet",
                             badge="▶ Ready" if ep.video else "In progress")
            card.clicked.connect(lambda e=ep: self.studio.show_episode(e.root))
            if ep.video:
                card.actions.addWidget(button("Watch", "Primary", lambda _=False, e=ep: self.studio.show_episode(
                    e.root, play=True)))
            else:
                card.actions.addWidget(button("Continue", "Primary", lambda _=False, e=ep: self.studio.continue_episode(
                    e.root)))
            card.actions.addWidget(button("Edit", None, lambda _=False, e=ep: self.studio.edit_episode(e.root)))
            card.actions.addWidget(button("Folder", None, lambda _=False, e=ep: self.studio.open_path(e.root)))
            self.gallery.addWidget(card)
        self.gallery_host.updateGeometry()

    # ------------------------------------------------------------------- make
    def quality(self) -> str:
        return "preview" if self.speed.value() == "Quick" else "standard"

    def language(self) -> str:
        return "ur" if self.lang.value() == "Urdu" else "en"

    def _update_estimate(self) -> None:
        text = self.box.toPlainText().strip()
        seconds, lines, is_script = 100.0, 18, False
        if text and looks_like_script(text):
            p = parse_script(text)
            seconds = max(60.0, sum(s.estimated_duration for s in p.scenes))
            lines, is_script = len(p.all_dialogue_events()), True
        minutes = estimate_minutes(seconds, self.quality(), lines)
        extra = "" if (not text or is_script) else " + 2–4 min to write the story"
        what = "Full script detected. " if is_script else ""
        self.estimate.setText(f"{what}Takes {human_duration(minutes)} on this computer{extra}. "
                              "You'll get a notification when it's ready.")

    def _set_busy(self, busy: bool) -> None:
        self.make_btn.setEnabled(not busy)
        self.make_btn.setText("Working…" if busy else "✦  Make my cartoon")

    def _make(self) -> None:
        text = self.box.toPlainText().strip()
        if not text:
            self.state.toast.emit("Type a story idea first.")
            self.box.setFocus()
            return
        self.state.settings.quality = self.quality()
        self.studio.make_cartoon(text, self.language(), new_episode=True)

    def focus_box(self) -> None:
        self.box.setFocus(Qt.OtherFocusReason)
