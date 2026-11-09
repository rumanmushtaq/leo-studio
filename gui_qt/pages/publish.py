"""Publish: title, description, thumbnail maker, and upload to the owner's YouTube channel."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QTextEdit, QProgressBar, QScrollArea, QSlider, QVBoxLayout, QWidget)

from core.script_parser import ScriptParser
from engines import youtube_uploader as yt
from engines.thumbnail_maker import grab_frame, make_thumbnail
from gui_qt import theme
from gui_qt.widgets import Card, button, fmt_time, label, rounded_pixmap
from gui_qt.workers import TaskWorker

GUIDE = """<b>One-time setup (free, about 10 minutes)</b><ol>
<li>Open <a href="https://console.cloud.google.com/">console.cloud.google.com</a> with the Google account of your
channel and create a project (any name).</li>
<li>APIs &amp; Services → Library → enable <b>YouTube Data API v3</b>.</li>
<li>OAuth consent screen → External → add your own e-mail as a <b>test user</b>.</li>
<li>Credentials → Create credentials → OAuth client ID → <b>Desktop app</b> → Download JSON.</li>
<li>Here: <b>Choose client file…</b>, then <b>Sign in</b> (opens your browser).</li></ol>
Videos upload as <b>Private</b> unless you choose otherwise, so you can check them on YouTube first."""
PRIVACY = {"private": "Private (only you)", "unlisted": "Unlisted (people with the link)", "public": "Public"}


def default_text(ep) -> tuple[str, str, list[str]]:
    """Title, description and tags drafted from the episode's script."""
    title = ep.name.replace("_", " ").title()
    lines, chars = [], set()
    if ep.script:
        parsed = ScriptParser().parse(ep.script)
        for s in parsed.scenes:
            chars.update(s.characters)
        narr = [e.text for e in parsed.all_dialogue_events() if e.kind == "narration"]
        lines = narr[:3]
        if parsed.scenes:
            title = f"{title} | {parsed.scenes[0].title}"
    names = ", ".join(sorted(c.replace("_", " ").title() for c in chars if c != "narrator"))
    desc = "\n".join(lines)
    if names:
        desc += f"\n\nCharacters: {names}"
    desc += ("\n\nA 3D cartoon for kids, made with Leo 3D AI Cartoon Studio. "
             "Voices and animation are computer-generated.")
    tags = ["cartoon", "kids cartoon", "3d animation", "urdu cartoon", "moral story", "bachon ki kahani"]
    return title[:100], desc.strip(), tags


class PublishPage(QWidget):
    def __init__(self, state, studio):
        super().__init__()
        self.setObjectName("Page")
        self.state = state
        self.studio = studio
        self._task: TaskWorker | None = None
        self._frame: Path | None = None
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
        head = QHBoxLayout()
        head.addWidget(label("Publish to YouTube", "PageTitle"))
        head.addStretch(1)
        self.episode_lbl = label("", muted=True)
        head.addWidget(self.episode_lbl)
        lay.addLayout(head)
        cols = QHBoxLayout()
        cols.setSpacing(16)

        left = QVBoxLayout()
        details = Card()
        details.lay.addWidget(label("Video details", "SectionTitle"))
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.title = QLineEdit()
        self.title.setMaxLength(100)
        self.title.setFont(theme.urdu_font(12))
        form.addRow("Title", self.title)
        self.desc = QTextEdit()
        self.desc.setAcceptRichText(False)
        self.desc.setFont(theme.urdu_font(12))
        self.desc.setMinimumHeight(170)
        theme.auto_direction(self.desc)
        form.addRow("Description", self.desc)
        self.tags = QLineEdit()
        self.tags.setPlaceholderText("comma, separated, tags")
        form.addRow("Tags", self.tags)
        self.privacy = QComboBox()
        for k, v in PRIVACY.items():
            self.privacy.addItem(v, k)
        form.addRow("Visibility", self.privacy)
        self.kids = QCheckBox("Made for kids (required by law for children's videos)")
        self.kids.setChecked(True)
        form.addRow("", self.kids)
        self.synthetic = QCheckBox("Contains AI-generated (altered or synthetic) content")
        self.synthetic.setChecked(True)
        form.addRow("", self.synthetic)
        details.lay.addLayout(form)
        left.addWidget(details)

        account = Card()
        account.lay.addWidget(label("YouTube account", "SectionTitle"))
        self.account_status = label("", wrap=True)
        account.lay.addWidget(self.account_status)
        arow = QHBoxLayout()
        self.client_btn = button("Choose client file…", None, self._choose_client)
        self.signin_btn = button("Sign in", None, self._sign_in)
        self.signout_btn = button("Sign out", None, self._sign_out)
        for b in (self.client_btn, self.signin_btn, self.signout_btn):
            arow.addWidget(b)
        arow.addStretch(1)
        account.lay.addLayout(arow)
        guide = QLabel(GUIDE)
        guide.setWordWrap(True)
        guide.setOpenExternalLinks(True)
        guide.setTextFormat(Qt.RichText)
        guide.setStyleSheet(f"color: {theme.MUTED};")
        account.lay.addWidget(guide)
        left.addWidget(account)
        left.addStretch(1)
        cols.addLayout(left, 1)

        right = QVBoxLayout()
        thumb = Card()
        thumb.lay.addWidget(label("Thumbnail", "SectionTitle"))
        self.thumb_view = QLabel()
        self.thumb_view.setAlignment(Qt.AlignCenter)
        self.thumb_view.setPixmap(rounded_pixmap(None, QSize(512, 288), 12, "Thumbnail preview"))
        thumb.lay.addWidget(self.thumb_view)
        trow = QHBoxLayout()
        trow.addWidget(label("Frame", muted=True))
        self.frame_slider = QSlider(Qt.Horizontal)
        self.frame_slider.setRange(0, 1000)
        self.frame_slider.setValue(400)
        self.frame_slider.valueChanged.connect(lambda _: self._frame_timer.start(350))
        trow.addWidget(self.frame_slider, 1)
        self.frame_time = label("", muted=True)
        trow.addWidget(self.frame_time)
        thumb.lay.addLayout(trow)
        self.thumb_title = QLineEdit()
        self.thumb_title.setFont(theme.urdu_font(12))
        self.thumb_title.setPlaceholderText("Big text on the thumbnail (Urdu or English)")
        self.thumb_title.textChanged.connect(lambda _: self._thumb_timer.start(450))
        thumb.lay.addWidget(self.thumb_title)
        orow = QHBoxLayout()
        self.text_pos = QComboBox()
        self.text_pos.addItem("Text at bottom", "bottom")
        self.text_pos.addItem("Text at top", "top")
        self.text_pos.currentIndexChanged.connect(lambda _: self._thumb_timer.start(100))
        orow.addWidget(self.text_pos)
        self.text_col = QComboBox()
        for name, c in (("Yellow", "#ffd23f"), ("White", "#ffffff"), ("Orange", "#ff8a3d"), ("Cyan", "#5ee7ff")):
            self.text_col.addItem(name, c)
        self.text_col.currentIndexChanged.connect(lambda _: self._thumb_timer.start(100))
        orow.addWidget(self.text_col)
        orow.addStretch(1)
        orow.addWidget(button("Save thumbnail…", None, self._save_thumb))
        thumb.lay.addLayout(orow)
        right.addWidget(thumb)

        up = Card()
        up.lay.addWidget(label("Upload", "SectionTitle"))
        self.upload_status = label("", muted=True, wrap=True)
        self.upload_status.setTextFormat(Qt.RichText)
        self.upload_status.setOpenExternalLinks(True)
        up.lay.addWidget(self.upload_status)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.hide()
        up.lay.addWidget(self.bar)
        self.upload_btn = button("⇪  Upload to YouTube", "Primary", self._upload)
        up.lay.addWidget(self.upload_btn, 0, Qt.AlignRight)
        right.addWidget(up)
        right.addStretch(1)
        cols.addLayout(right, 1)
        lay.addLayout(cols)

        self._frame_timer = QTimer(self, singleShot=True, timeout=self._grab)
        self._thumb_timer = QTimer(self, singleShot=True, timeout=self._render_thumb)
        state.episode_changed.connect(self.load_episode)
        self.load_episode(state.episode)

    # ------------------------------------------------------------- episode
    def _thumb_path(self) -> Path | None:
        ep = self.state.episode
        return ep.root / "youtube_thumbnail.jpg" if ep else None

    def load_episode(self, ep) -> None:
        self._refresh_account()
        has_video = bool(ep and ep.video)
        self.upload_btn.setEnabled(has_video and yt.libraries_available())
        self.frame_slider.setEnabled(has_video)
        if not has_video:
            self.episode_lbl.setText("Open a finished cartoon (Home → Watch) to publish it.")
            return
        self.episode_lbl.setText(f"{ep.name} · {fmt_time(ep.duration)}")
        title, desc, tags = default_text(ep)
        self.title.setText(title)
        self.desc.setPlainText(desc)
        self.tags.setText(", ".join(tags))
        self.thumb_title.setText(ep.name.replace("_", " ").title())
        self.upload_status.setText("Ready to upload." if yt.is_signed_in() else "Sign in to upload.")
        self._frame = None
        if self.isVisible():
            self._grab()

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        if self._frame is None and self.state.episode and self.state.episode.video:
            QTimer.singleShot(0, self._grab)

    def _grab(self) -> None:
        ep = self.state.episode
        if not ep or not ep.video:
            return
        t = ep.duration * self.frame_slider.value() / 1000
        self.frame_time.setText(fmt_time(t))
        try:
            self._frame = grab_frame(ep.video, t, ep.root / "temp" / "thumb_frame.png")
        except Exception as exc:  # shown inline; the rest of the page keeps working
            self.upload_status.setText(f"Could not read a frame: {exc}")
            return
        self._render_thumb()

    def _render_thumb(self) -> None:
        out = self._thumb_path()
        if not self._frame or not out:
            return
        make_thumbnail(self._frame, self.thumb_title.text(), out, self.text_col.currentData(),
                       self.text_pos.currentData())
        self.thumb_view.setPixmap(rounded_pixmap(out, QSize(512, 288), 12))

    def _save_thumb(self) -> None:
        src = self._thumb_path()
        if not src or not src.exists():
            return
        f, _ = QFileDialog.getSaveFileName(self, "Save thumbnail", str(Path.home() / "thumbnail.jpg"), "JPEG (*.jpg)")
        if f:
            Path(f).write_bytes(src.read_bytes())
            self.state.toast.emit("Thumbnail saved")

    # -------------------------------------------------------------- account
    def _refresh_account(self) -> None:
        if not yt.libraries_available():
            self.account_status.setText("The Google upload library is not installed (pip install -r requirements.txt).")
            for b in (self.client_btn, self.signin_btn, self.signout_btn):
                b.setEnabled(False)
            return
        signed, client = yt.is_signed_in(), yt.has_client()
        self.account_status.setText("✓ Signed in — ready to upload" if signed else
                                    "Client file added — press Sign in" if client else "Not set up yet")
        self.account_status.setStyleSheet(f"color: {theme.OK if signed else theme.MUTED};")
        self.signin_btn.setEnabled(client and not signed)
        self.signout_btn.setEnabled(signed)

    def _choose_client(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Google OAuth client (Desktop app) JSON", str(Path.home()),
                                           "JSON (*.json)")
        if f:
            try:
                yt.set_client_file(Path(f))
            except (yt.YouTubeError, ValueError, OSError) as exc:
                self.studio.error("Client file", str(exc))
            self._refresh_account()

    def _sign_in(self) -> None:
        self._run(lambda progress: yt.credentials(interactive=True), "Waiting for you to sign in in the browser…",
                  lambda _: (self._refresh_account(), self.state.toast.emit("Signed in to YouTube")))

    def _sign_out(self) -> None:
        yt.sign_out()
        self._refresh_account()

    # --------------------------------------------------------------- upload
    def _meta(self) -> yt.VideoMeta:
        return yt.VideoMeta(title=self.title.text(), description=self.desc.toPlainText(),
                            tags=[t for t in self.tags.text().split(",") if t.strip()],
                            privacy=self.privacy.currentData(), made_for_kids=self.kids.isChecked(),
                            synthetic=self.synthetic.isChecked(),
                            language="ur" if any("؀" <= ch <= "ۿ" for ch in self.title.text()
                                                 + self.desc.toPlainText()) else "en")

    def _upload(self) -> None:
        ep = self.state.episode
        if not ep or not ep.video:
            return
        meta = self._meta()
        issues = meta.problems()
        if issues:
            self.studio.error("Check the details", "\n".join(issues))
            return
        if not yt.has_client():
            self.studio.error("Set up YouTube first", "Choose your Google OAuth client file (see the steps).")
            return
        thumb = self._thumb_path()
        self._run(lambda progress: yt.upload(ep.video, meta, thumb if thumb and thumb.exists() else None, progress),
                  "Starting upload…", self._uploaded)

    def _uploaded(self, res: dict) -> None:
        note = f"<br>{res['note']}" if res.get("note") else ""
        self.upload_status.setText(f"✓ Uploaded: <a href='{res['url']}'>{res['url']}</a> "
                                   f"({self.privacy.currentText()}){note}")
        self.state.toast.emit("Uploaded to YouTube")
        self._refresh_account()

    def _run(self, fn, start_msg: str, on_done) -> None:
        if self._task and self._task.isRunning():
            return
        self.upload_status.setText(start_msg)
        self.bar.setValue(0)
        self.bar.show()
        self.upload_btn.setEnabled(False)
        self._task = TaskWorker(fn)
        self._task.progress.connect(lambda f, m: (self.bar.setValue(int(f * 1000)), self.upload_status.setText(m)))
        self._task.done.connect(lambda r: (self.bar.hide(), self.upload_btn.setEnabled(True), on_done(r)))
        self._task.failed.connect(lambda e: (self.bar.hide(), self.upload_btn.setEnabled(True),
                                             self.upload_status.setText("✗ " + e)))
        self._task.start()
