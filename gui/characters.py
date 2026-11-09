"""Character editor window: view designs, edit colours/size, import a 3D model."""
from __future__ import annotations

import copy
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox

import customtkinter as ctk
from PIL import Image

from core.character_manager import CharacterRegistry, slugify
from gui.components import ACCENT, ACCENT_HOVER, MUTED
from utils.config import CHARACTER_LIBRARY

COLOR_FIELDS = [("Skin", ("skin",)), ("Hair", ("hair", "color")), ("Eyes", ("eye_color",)),
                ("Shirt / suit", ("costume", "shirt")), ("Sleeves", ("costume", "sleeves")),
                ("Trousers", ("costume", "pants")), ("Shoes", ("costume", "shoes"))]
MODEL_TYPES = [("3D character", "*.glb *.gltf *.fbx *.blend"), ("All files", "*.*")]


def _get(d: dict, path: tuple):
    for k in path:
        d = d.get(k, {}) if isinstance(d, dict) else {}
    return d if isinstance(d, list) else None


def _set(d: dict, path: tuple, value) -> None:
    for k in path[:-1]:
        d = d.setdefault(k, {})
    d[path[-1]] = value


def _hex(rgb) -> str:
    rgb = rgb or [0.5, 0.5, 0.5]
    return "#%02x%02x%02x" % tuple(int(max(0, min(1, c)) * 255) for c in rgb[:3])


class CharacterWindow(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Characters")
        self.geometry("1200x660")
        self.transient(master)
        self.registry = CharacterRegistry()
        for cid in self.registry.presets:
            if not self.registry.presets[cid].get("voice_only"):
                self.registry.get_or_create(cid)
        self.current: str | None = None
        self.data: dict = {}
        self._img = None
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(self, width=220)
        left.grid(row=0, column=0, sticky="nsw", padx=12, pady=12)
        ctk.CTkLabel(left, text="Characters", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=10,
                                                                                             pady=(10, 6))
        self.list_frame = ctk.CTkScrollableFrame(left, width=200, height=470)
        self.list_frame.pack(fill="both", expand=True, padx=6)
        ctk.CTkButton(left, text="+ New from 3D model…", command=self._new_from_model).pack(fill="x", padx=8, pady=8)

        right = ctk.CTkFrame(self)
        right.grid(row=0, column=1, sticky="nsew", padx=(0, 12), pady=12)
        right.grid_columnconfigure(1, weight=1)
        self.preview = ctk.CTkLabel(right, text="", width=300, height=300)
        self.preview.grid(row=0, column=0, rowspan=12, padx=12, pady=12, sticky="n")
        self.title_lbl = ctk.CTkLabel(right, text="", font=ctk.CTkFont(size=20, weight="bold"), anchor="w")
        self.title_lbl.grid(row=0, column=1, sticky="ew", pady=(12, 2))
        self.desc = ctk.CTkLabel(right, text="", text_color=MUTED, anchor="w", justify="left", wraplength=440)
        self.desc.grid(row=1, column=1, sticky="ew")
        self.swatches: dict[str, ctk.CTkButton] = {}
        grid = ctk.CTkFrame(right, fg_color="transparent")
        grid.grid(row=2, column=1, sticky="ew", pady=8)
        for i, (label, path) in enumerate(COLOR_FIELDS):
            ctk.CTkLabel(grid, text=label, anchor="w", width=110).grid(row=i // 2, column=(i % 2) * 2, sticky="w",
                                                                         pady=3)
            b = ctk.CTkButton(grid, text="", width=90, height=24, command=lambda p=path: self._pick(p))
            b.grid(row=i // 2, column=(i % 2) * 2 + 1, padx=(0, 18), pady=3)
            self.swatches[label] = b
        row = ctk.CTkFrame(right, fg_color="transparent")
        row.grid(row=3, column=1, sticky="ew", pady=4)
        ctk.CTkLabel(row, text="Height (m)").pack(side="left")
        self.height = ctk.CTkSlider(row, from_=0.9, to=2.1, command=lambda v: self._set_num(("height",), v))
        self.height.pack(side="left", padx=8)
        self.height_lbl = ctk.CTkLabel(row, text="", width=40)
        self.height_lbl.pack(side="left")
        row2 = ctk.CTkFrame(right, fg_color="transparent")
        row2.grid(row=4, column=1, sticky="ew", pady=4)
        ctk.CTkLabel(row2, text="Build width").pack(side="left")
        self.width_sl = ctk.CTkSlider(row2, from_=0.75, to=1.5, command=lambda v: self._set_num(("build", "width"), v))
        self.width_sl.pack(side="left", padx=8)
        ctk.CTkLabel(row2, text="Belly").pack(side="left", padx=(12, 0))
        self.belly_sl = ctk.CTkSlider(row2, from_=0.0, to=0.6, command=lambda v: self._set_num(("build", "belly"), v))
        self.belly_sl.pack(side="left", padx=8)
        self.model_lbl = ctk.CTkLabel(right, text="", text_color=MUTED, anchor="w", justify="left", wraplength=440)
        self.model_lbl.grid(row=5, column=1, sticky="ew", pady=(10, 2))
        mrow = ctk.CTkFrame(right, fg_color="transparent")
        mrow.grid(row=6, column=1, sticky="ew")
        ctk.CTkButton(mrow, text="Use 3D model file…", width=160, command=self._attach_model).pack(side="left")
        self.keep_head = ctk.CTkCheckBox(mrow, text="Keep the model's own head/face", command=self._toggle_head)
        self.keep_head.pack(side="left", padx=10)
        ctk.CTkButton(mrow, text="Remove model", width=110, fg_color="#253048", hover_color="#2f3c5a",
                      command=self._detach_model).pack(side="left")
        ctk.CTkLabel(right, text="Changes rebuild only this character the next time you generate. "
                                 "Imported models need a humanoid skeleton (Mixamo, UE/Quaternius).",
                     text_color=MUTED, anchor="w", justify="left", wraplength=440).grid(row=7, column=1, sticky="ew",
                                                                                         pady=10)
        brow = ctk.CTkFrame(right, fg_color="transparent")
        brow.grid(row=8, column=1, sticky="e", pady=6)
        ctk.CTkButton(brow, text="Reset to original", fg_color="#253048", hover_color="#2f3c5a",
                      command=self._reset).pack(side="left", padx=6)
        ctk.CTkButton(brow, text="Save", fg_color=ACCENT, hover_color=ACCENT_HOVER, command=self._save).pack(
            side="left")
        self._refresh_list()

    # ------------------------------------------------------------------ list
    def _refresh_list(self) -> None:
        for w in self.list_frame.winfo_children():
            w.destroy()
        ids = sorted((cid for cid, s in self.registry.characters.items() if not s.voice_only),
                     key=lambda c: self.registry.characters[c].name)
        for cid in ids:
            ctk.CTkButton(self.list_frame, text=self.registry.characters[cid].name, anchor="w",
                          fg_color="#1f2a3d" if cid != self.current else ACCENT,
                          command=lambda c=cid: self._select(c)).pack(fill="x", pady=2)
        if ids and self.current is None:
            self._select(ids[0])

    def _select(self, cid: str) -> None:
        self.current = cid
        self.data = copy.deepcopy(self.registry.characters[cid].data)
        self._show()
        self._refresh_list()

    def _show(self) -> None:
        d = self.data
        self.title_lbl.configure(text=d.get("name", self.current))
        self.desc.configure(text=d.get("appearance") or d.get("personality") or "")
        for label, path in COLOR_FIELDS:
            c = _hex(_get(d, path))
            self.swatches[label].configure(fg_color=c, hover_color=c)
        self.height.set(float(d.get("height", 1.7)))
        self.height_lbl.configure(text=f"{float(d.get('height', 1.7)):.2f}")
        self.width_sl.set(float(d.get("build", {}).get("width", 1.0)))
        self.belly_sl.set(float(d.get("build", {}).get("belly", 0.0)))
        mf = d.get("model_file")
        self.model_lbl.configure(text=f"3D model: {mf}" if mf else "Body: built-in CC0 base body with cartoon head")
        self.keep_head.select() if d.get("keep_head") else self.keep_head.deselect()
        ref = CHARACTER_LIBRARY / f"{self.current}_reference.png"
        if ref.exists():
            img = Image.open(ref)
            self._img = ctk.CTkImage(light_image=img, dark_image=img, size=(300, 300))
            self.preview.configure(image=self._img, text="")
        else:
            self.preview.configure(image=None, text="Preview appears\nafter the first build")

    # --------------------------------------------------------------- editing
    def _pick(self, path: tuple) -> None:
        res = colorchooser.askcolor(color=_hex(_get(self.data, path)), parent=self)
        if res and res[0]:
            _set(self.data, path, [round(c / 255, 3) for c in res[0]])
            if path == ("costume", "shirt") and not _get(self.data, ("costume", "sleeves")):
                _set(self.data, ("costume", "sleeves"), [round(c / 255, 3) for c in res[0]])
            self._show()

    def _set_num(self, path: tuple, value: float) -> None:
        _set(self.data, path, round(float(value), 3))
        if path == ("height",):
            self.height_lbl.configure(text=f"{float(value):.2f}")

    def _attach_model(self) -> None:
        f = filedialog.askopenfilename(parent=self, filetypes=MODEL_TYPES)
        if f:
            self.data["model_file"] = str(Path(f).resolve())
            self.data["recolor"] = not self.data.get("keep_head")
            self._show()

    def _toggle_head(self) -> None:
        self.data["keep_head"] = bool(self.keep_head.get())
        if self.data.get("model_file"):
            self.data["recolor"] = not self.data["keep_head"]

    def _detach_model(self) -> None:
        for k in ("model_file", "keep_head", "recolor"):
            self.data.pop(k, None)
        self._show()

    def _new_from_model(self) -> None:
        f = filedialog.askopenfilename(parent=self, filetypes=MODEL_TYPES)
        if not f:
            return
        dialog = ctk.CTkInputDialog(text="Character name as used in the script (e.g. Zara or زارا):",
                                    title="New character")
        name = (dialog.get_input() or "").strip()
        if not name:
            return
        spec = self.registry.get_or_create(name)
        data = copy.deepcopy(spec.data)
        data.update({"name": name, "model_file": str(Path(f).resolve()), "keep_head": True, "recolor": False})
        data.setdefault("aliases", []).append(name.lower())
        self.registry.import_character(spec.id or slugify(name), data)
        self.current = spec.id
        self._select(spec.id)

    def _reset(self) -> None:
        if self.current in self.registry.presets:
            self.data = copy.deepcopy(self.registry.presets[self.current])
            self.registry.characters[self.current].data = copy.deepcopy(self.data)
            self.registry.save()
        self._show()

    def _save(self) -> None:
        if not self.current:
            return
        try:
            self.registry.import_character(self.current, self.data)
        except Exception as exc:  # surfaced to the user, never silently ignored
            messagebox.showerror("Save failed", str(exc), parent=self)
            return
        messagebox.showinfo("Saved", f"{self.data.get('name')} saved. It will be rebuilt on the next generation.",
                            parent=self)
