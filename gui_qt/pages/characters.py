"""Characters: gallery of the cast with their 3D previews; change colours, size, or use a 3D model."""
from __future__ import annotations

import copy
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QFileDialog, QGridLayout, QHBoxLayout, QInputDialog,
                               QLabel, QScrollArea, QSlider, QSplitter, QVBoxLayout, QWidget)

from core.character_manager import CharacterRegistry, slugify
from gui_qt.widgets import Card, FlowLayout, ThumbCard, button, label, rounded_pixmap
from utils.config import CHARACTER_LIBRARY

COLOR_FIELDS = [("Skin", ("skin",)), ("Hair", ("hair", "color")), ("Eyes", ("eye_color",)),
                ("Shirt / suit", ("costume", "shirt")), ("Sleeves", ("costume", "sleeves")),
                ("Trousers", ("costume", "pants")), ("Shoes", ("costume", "shoes"))]
SLIDERS = [("Height", ("height",), 0.9, 2.1, 1.7, "{:.2f} m"), ("Build", ("build", "width"), 0.75, 1.5, 1.0, "{:.2f}×"),
           ("Belly", ("build", "belly"), 0.0, 0.6, 0.0, "{:.2f}")]
MODEL_FILTER = "3D character (*.glb *.gltf *.fbx *.blend);;All files (*)"


def _get(d: dict, path: tuple, default=None):
    for k in path:
        if not isinstance(d, dict):
            return default
        d = d.get(k, None)
        if d is None:
            return default
    return d


def _set(d: dict, path: tuple, value) -> None:
    for k in path[:-1]:
        d = d.setdefault(k, {})
    d[path[-1]] = value


def _hex(rgb) -> str:
    rgb = rgb if isinstance(rgb, list) and len(rgb) >= 3 else [0.5, 0.5, 0.5]
    return "#%02x%02x%02x" % tuple(int(max(0, min(1, c)) * 255) for c in rgb[:3])


class CharactersPage(QWidget):
    def __init__(self, state, studio):
        super().__init__()
        self.setObjectName("Page")
        self.state = state
        self.studio = studio
        self.current: str | None = None
        self.data: dict = {}
        self.cards: dict[str, ThumbCard] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 24, 32, 24)
        lay.setSpacing(14)
        head = QHBoxLayout()
        head.addWidget(label("Characters", "PageTitle"))
        head.addWidget(label("  Your cast. Every episode uses the same look.", "PageSubtitle"))
        head.addStretch(1)
        head.addWidget(button("+ New from 3D model…", None, self._new_from_model))
        lay.addLayout(head)

        split = QSplitter(Qt.Horizontal)
        split.setHandleWidth(12)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        self.grid = FlowLayout(host, spacing=14)
        scroll.setWidget(host)
        split.addWidget(scroll)

        detail = Card(margins=20)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setFixedSize(300, 300)
        top = QHBoxLayout()
        top.addWidget(self.preview)
        info = QVBoxLayout()
        self.name = label("", "PageTitle")
        self.role = label("", muted=True)
        self.desc = label("", muted=True, wrap=True)
        info.addWidget(self.name)
        info.addWidget(self.role)
        info.addWidget(self.desc, 1)
        top.addLayout(info, 1)
        detail.lay.addLayout(top)
        detail.lay.addWidget(label("Colours", "SectionTitle"))
        colours = QGridLayout()
        colours.setHorizontalSpacing(12)
        self.swatches = {}
        for i, (name, path) in enumerate(COLOR_FIELDS):
            b = button("", "Swatch", lambda _=False, p=path: self._pick(p), f"Change {name.lower()} colour")
            b.setFixedSize(54, 30)
            colours.addWidget(label(name, muted=True), i // 2, (i % 2) * 2)
            colours.addWidget(b, i // 2, (i % 2) * 2 + 1)
            self.swatches[path] = b
        colours.setColumnStretch(4, 1)
        detail.lay.addLayout(colours)
        detail.lay.addWidget(label("Body", "SectionTitle"))
        self.sliders = {}
        for name, path, lo, hi, default, fmt in SLIDERS:
            row = QHBoxLayout()
            row.addWidget(label(name, muted=True))
            sl = QSlider(Qt.Horizontal)
            sl.setRange(int(lo * 100), int(hi * 100))
            val = label("", muted=True)
            val.setMinimumWidth(60)
            sl.valueChanged.connect(lambda v, p=path, lab=val, f=fmt: self._slide(p, v / 100, lab, f))
            row.addWidget(sl, 1)
            row.addWidget(val)
            detail.lay.addLayout(row)
            self.sliders[path] = (sl, default)
        detail.lay.addWidget(label("3D model", "SectionTitle"))
        self.model = label("", muted=True, wrap=True)
        detail.lay.addWidget(self.model)
        mrow = QHBoxLayout()
        mrow.addWidget(button("Use 3D model file…", None, self._attach))
        self.keep_head = QCheckBox("Keep the model's own head/face")
        self.keep_head.toggled.connect(self._toggle_head)
        mrow.addWidget(self.keep_head)
        mrow.addWidget(button("Remove model", None, self._detach))
        mrow.addStretch(1)
        detail.lay.addLayout(mrow)
        detail.lay.addWidget(label("Changes rebuild only this character on the next cartoon. Imported models need "
                                   "a humanoid skeleton (Mixamo or Unreal/Quaternius bone names).", muted=True,
                                   wrap=True))
        detail.lay.addStretch(1)
        brow = QHBoxLayout()
        brow.addStretch(1)
        brow.addWidget(button("Reset to original", None, self._reset))
        self.save_btn = button("Save changes", "Primary", self._save)
        brow.addWidget(self.save_btn)
        detail.lay.addLayout(brow)
        dscroll = QScrollArea()
        dscroll.setWidgetResizable(True)
        dscroll.setWidget(detail)
        split.addWidget(dscroll)
        split.setSizes([560, 620])
        lay.addWidget(split, 1)
        self.reload()

    # ---------------------------------------------------------------- list
    def reload(self) -> None:
        self.registry = CharacterRegistry()
        for cid, d in self.registry.presets.items():
            if not d.get("voice_only"):
                self.registry.get_or_create(cid)
        self.grid.clear()
        self.cards = {}
        ids = sorted((c for c, s in self.registry.characters.items() if not s.voice_only),
                     key=lambda c: self.registry.characters[c].name)
        for cid in ids:
            spec = self.registry.characters[cid]
            ref = CHARACTER_LIBRARY / f"{cid}_reference.png"
            card = ThumbCard(spec.name, spec.role.replace("_", " ").title(), ref if ref.exists() else None,
                             QSize(150, 150), "Preview after\nfirst build")
            card.clicked.connect(lambda c=cid: self.select(c))
            self.grid.addWidget(card)
            self.cards[cid] = card
        if ids:
            self.select(self.current if self.current in ids else ids[0])

    def select(self, cid: str) -> None:
        self.current = cid
        self.data = copy.deepcopy(self.registry.characters[cid].data)
        for c, card in self.cards.items():
            card.set_selected(c == cid)
        self._show()

    def _show(self) -> None:
        d = self.data
        self.name.setText(d.get("name", self.current))
        self.role.setText((d.get("role") or "").replace("_", " ").title())
        self.desc.setText(d.get("appearance") or d.get("personality") or "")
        for path, b in self.swatches.items():
            c = _hex(_get(d, path))
            b.setStyleSheet(f"background: {c};")
        for path, (sl, default) in self.sliders.items():
            sl.blockSignals(True)
            sl.setValue(int(float(_get(d, path, default)) * 100))
            sl.blockSignals(False)
            sl.valueChanged.emit(sl.value())
        mf = d.get("model_file")
        self.model.setText(f"Uses your model: {Path(mf).name}" if mf else
                           "Built-in CC0 base body with a cartoon head.")
        self.keep_head.blockSignals(True)
        self.keep_head.setChecked(bool(d.get("keep_head")))
        self.keep_head.blockSignals(False)
        ref = CHARACTER_LIBRARY / f"{self.current}_reference.png"
        self.preview.setPixmap(rounded_pixmap(ref if ref.exists() else None, QSize(300, 300), 16,
                                              "Preview appears after the first build"))

    # ------------------------------------------------------------- editing
    def _pick(self, path: tuple) -> None:
        c = QColorDialog.getColor(QColor(_hex(_get(self.data, path))), self, "Choose colour")
        if c.isValid():
            rgb = [round(c.redF(), 3), round(c.greenF(), 3), round(c.blueF(), 3)]
            _set(self.data, path, rgb)
            if path == ("costume", "shirt") and not _get(self.data, ("costume", "sleeves")):
                _set(self.data, ("costume", "sleeves"), rgb)
            self._show()

    def _slide(self, path: tuple, value: float, lab: QLabel, fmt: str) -> None:
        lab.setText(fmt.format(value))
        if self.data and abs(float(_get(self.data, path, value)) - value) > 1e-6:
            _set(self.data, path, round(value, 3))

    def _attach(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Choose a rigged 3D character", "", MODEL_FILTER)
        if f:
            self.data["model_file"] = str(Path(f).resolve())
            self.data["recolor"] = not self.data.get("keep_head")
            self._show()

    def _toggle_head(self, on: bool) -> None:
        self.data["keep_head"] = bool(on)
        if self.data.get("model_file"):
            self.data["recolor"] = not on

    def _detach(self) -> None:
        for k in ("model_file", "keep_head", "recolor"):
            self.data.pop(k, None)
        self._show()

    def _new_from_model(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Choose a rigged 3D character", "", MODEL_FILTER)
        if not f:
            return
        name, ok = QInputDialog.getText(self, "New character", "Name as used in the script (e.g. Zara or زارا):")
        if not ok or not name.strip():
            return
        name = name.strip()
        spec = self.registry.get_or_create(name)
        data = copy.deepcopy(spec.data)
        data.update({"name": name, "model_file": str(Path(f).resolve()), "keep_head": True, "recolor": False})
        data.setdefault("aliases", []).append(name.lower())
        self.registry.import_character(spec.id or slugify(name), data)
        self.current = spec.id
        self.reload()

    def _reset(self) -> None:
        if self.current in self.registry.presets:
            self.data = copy.deepcopy(self.registry.presets[self.current])
            self._show()
            self.state.toast.emit("Original look restored — press Save to keep it")

    def _save(self) -> None:
        if not self.current:
            return
        try:
            self.registry.import_character(self.current, self.data)
        except Exception as exc:  # surfaced to the user, never silently ignored
            self.studio.error("Save failed", str(exc))
            return
        self.state.toast.emit(f"{self.data.get('name')} saved — rebuilt on the next cartoon")
