"""Storyboard: watch an episode, see every scene as a card, re-render one scene."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QMessageBox, QScrollArea, QSplitter, QVBoxLayout, QWidget

from core.character_manager import CharacterRegistry
from gui_qt.episodes import clear_scene_frames, find_episodes, scene_at
from gui_qt.widgets import Card, ThumbCard, VideoPlayer, button, fmt_time, label


class StoryboardPage(QWidget):
    def __init__(self, state, studio):
        super().__init__()
        self.setObjectName("Page")
        self.state = state
        self.studio = studio
        self.cards: dict[int, ThumbCard] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 24, 32, 24)
        lay.setSpacing(14)
        head = QHBoxLayout()
        head.addWidget(label("Storyboard", "PageTitle"))
        head.addSpacing(18)
        self.picker = QComboBox()
        self.picker.setMinimumWidth(280)
        self.picker.activated.connect(self._picked)
        head.addWidget(self.picker)
        head.addStretch(1)
        self.system_btn = button("Open in player", None, self._open_external)
        head.addWidget(self.system_btn)
        head.addWidget(button("Edit script", None, lambda: self.state.navigate.emit("script")))
        lay.addLayout(head)

        split = QSplitter(Qt.Vertical)
        split.setHandleWidth(10)
        self.player = VideoPlayer()
        self.player.position_changed.connect(self._highlight)
        split.addWidget(self.player)
        strip = Card(margins=12)
        top = QHBoxLayout()
        top.addWidget(label("Scenes", "SectionTitle"))
        self.info = label("", muted=True)
        top.addWidget(self.info, 1)
        strip.lay.addLayout(top)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.row_host = QWidget()
        self.row = QHBoxLayout(self.row_host)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(12)
        scroll.setWidget(self.row_host)
        scroll.setMinimumHeight(300)
        strip.lay.addWidget(scroll)
        split.addWidget(strip)
        split.setSizes([520, 320])
        lay.addWidget(split, 1)

        state.episode_changed.connect(self.show_episode)
        state.job_finished.connect(lambda _: self.reload_list())
        state.job_started.connect(lambda _: self._enable_rerender(False))
        self.reload_list()

    # ---------------------------------------------------------------- data
    def reload_list(self) -> None:
        self._episodes = find_episodes(self.state.settings.output_dir)
        self.picker.blockSignals(True)
        self.picker.clear()
        for ep in self._episodes:
            self.picker.addItem(ep.name.replace("_", " ").title() + ("" if ep.video else "  (unfinished)"),
                                str(ep.root))
        cur = self.state.episode
        if cur:
            i = self.picker.findData(str(cur.root))
            if i >= 0:
                self.picker.setCurrentIndex(i)
        self.picker.blockSignals(False)
        if cur is None and self._episodes:
            self.state.open_episode(self._episodes[0].root)

    def _picked(self, i: int) -> None:
        self.state.open_episode(self.picker.itemData(i))

    def show_episode(self, ep, play: bool = False) -> None:
        while self.row.count():
            it = self.row.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.cards = {}
        if ep is None:
            self.player.load(None)
            self.info.setText("Make a cartoon first — its scenes appear here.")
            return
        i = self.picker.findData(str(ep.root))
        if i < 0:
            self.reload_list()
        else:
            self.picker.setCurrentIndex(i)
        total = ep.duration or 1.0
        from gui_qt.episodes import make_thumbnail

        self.player.load(ep.video, [s.start / total for s in ep.scenes[1:]], make_thumbnail(ep))
        self.info.setText(f"{len(ep.scenes)} scenes · {fmt_time(ep.duration)}"
                          + ("" if ep.video else " · video not finished yet"))
        reg = CharacterRegistry()
        for s in ep.scenes:
            names = ", ".join(reg.get_or_create(c).name for c in s.characters[:4])
            status = "" if s.rendered else f"  ·  {100 * s.frames_done // max(1, s.frame_count)}% rendered"
            card = ThumbCard(f"{s.id}. {s.title}", f"{s.location.replace('_', ' ')} · {fmt_time(s.duration)}"
                             f"{status}\n{names}", ep.scene_thumb(s), QSize(240, 135), "Not rendered yet",
                             badge=fmt_time(s.start))
            card.setToolTip(s.first_line)
            card.clicked.connect(lambda sc=s: self.player.seek_to(sc.start + 0.05))
            rb = button("↻ Re-render", None, lambda _=False, sc=s: self._rerender(sc),
                        "Render only this scene again (for example after changing a character)")
            card.actions.addWidget(rb)
            card.rerender = rb
            self.row.addWidget(card)
            self.cards[s.id] = card
        self.row.addStretch(1)
        self._enable_rerender(not self.state.busy)
        if play and ep.video:
            self.player.seek_to(0.0)

    def _highlight(self, seconds: float) -> None:
        ep = self.state.episode
        if not ep:
            return
        cur = scene_at(ep, seconds)
        for sid, card in self.cards.items():
            card.set_selected(cur is not None and sid == cur.id)

    def _enable_rerender(self, on: bool) -> None:
        for card in self.cards.values():
            card.rerender.setEnabled(on)

    # ------------------------------------------------------------- actions
    def _rerender(self, scene) -> None:
        ep = self.state.episode
        if not ep or not ep.script:
            self.studio.error("Cannot re-render", "This episode has no saved script (projects/ folder).")
            return
        if QMessageBox.question(self, "Re-render scene",
                                f"Render scene {scene.id} “{scene.title}” again?\n\nThe other scenes are reused, "
                                "so this takes only the time for this scene plus the final video.") \
                != QMessageBox.Yes:
            return
        self.player.stop()
        clear_scene_frames(ep, scene.id)
        err = self.state.generate(ep.script, ep.name)
        if err:
            self.studio.error("Cannot start", err)
        else:
            self.state.navigate.emit("render")

    def _open_external(self) -> None:
        ep = self.state.episode
        if ep and ep.video:
            self.player.stop()
            self.studio.open_path(ep.video)
