"""Character registry: one persistent, reusable design per character.

Designs come from ``assets/characters/presets.json`` or are generated
deterministically from the character's name and script context, so the same
name always yields the same character. The registry is saved to
``assets/characters/registry.json`` and every built Blender asset is tracked by
a design hash; an unchanged design is never rebuilt, which keeps characters
identical across scenes and episodes.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from utils.config import CHARACTER_LIBRARY
from utils.logger import get_logger

log = get_logger("characters")

PRESETS_FILE = CHARACTER_LIBRARY / "presets.json"
REGISTRY_FILE = CHARACTER_LIBRARY / "registry.json"
# Bump when blender/character_builder.py changes how designs become geometry,
# so cached .blend assets are rebuilt once (and then reused again).
ASSET_VERSION = 8

_TRANSLIT = {
    "ا": "a", "آ": "aa", "ب": "b", "پ": "p", "ت": "t", "ٹ": "t", "ث": "s", "ج": "j", "چ": "ch",
    "ح": "h", "خ": "kh", "د": "d", "ڈ": "d", "ذ": "z", "ر": "r", "ڑ": "r", "ز": "z", "ژ": "zh",
    "س": "s", "ش": "sh", "ص": "s", "ض": "z", "ط": "t", "ظ": "z", "ع": "a", "غ": "gh", "ف": "f",
    "ق": "q", "ک": "k", "ك": "k", "گ": "g", "ل": "l", "م": "m", "ن": "n", "ں": "n", "و": "o",
    "ہ": "h", "ھ": "h", "ء": "", "ی": "i", "ي": "i", "ے": "e", "ئ": "i", "ۃ": "h", " ": "_",
}

PALETTE = [
    [0.85, 0.2, 0.2], [0.2, 0.55, 0.85], [0.95, 0.6, 0.1], [0.3, 0.7, 0.35], [0.6, 0.3, 0.75],
    [0.95, 0.85, 0.2], [0.1, 0.65, 0.65], [0.9, 0.4, 0.6], [0.45, 0.3, 0.2], [0.25, 0.25, 0.3],
]
SKINS = [[0.93, 0.74, 0.6], [0.85, 0.63, 0.47], [0.78, 0.55, 0.4], [0.62, 0.42, 0.3], [0.96, 0.8, 0.68]]
HAIR = [[0.08, 0.06, 0.05], [0.36, 0.2, 0.09], [0.55, 0.35, 0.15], [0.15, 0.1, 0.07]]


def slugify(name: str) -> str:
    """Stable ASCII id for any (Urdu or English) character name."""
    name = unicodedata.normalize("NFC", name).strip().lower()
    if re.search(r"[؀-ۿ]", name):
        name = "".join(_TRANSLIT.get(c, "") if not c.isascii() else c for c in name)
    slug = re.sub(r"[^a-z0-9]+", "_", name).strip("_")
    return slug or "char_" + hashlib.md5(name.encode()).hexdigest()[:6]


def _rng(seed: str):
    import random

    return random.Random(int(hashlib.sha256(seed.encode()).hexdigest()[:12], 16))


@dataclass
class CharacterSpec:
    id: str
    data: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.data.get("name", self.id)

    @property
    def role(self) -> str:
        return self.data.get("role", "neutral")

    @property
    def voice_only(self) -> bool:
        return bool(self.data.get("voice_only"))

    @property
    def voice(self) -> dict:
        return self.data.get("voice", {"pitch": 1.0, "rate": 1.0})

    def design_hash(self) -> str:
        """Hash of every field that changes the 3D model."""
        visual = {k: v for k, v in self.data.items()
                  if k not in ("voice", "personality", "aliases", "default_emotion", "asset", "asset_hash",
                               "reference_image")}
        payload = json.dumps([ASSET_VERSION, visual], sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


class CharacterRegistry:
    """Load/save the persistent registry and resolve script names to characters."""

    def __init__(self, registry_file: Path = REGISTRY_FILE, presets_file: Path = PRESETS_FILE):
        self.registry_file = Path(registry_file)
        presets = json.loads(Path(presets_file).read_text(encoding="utf-8"))
        self.presets: dict[str, dict] = presets["characters"]
        self.groups: dict[str, list[str]] = presets.get("groups", {})
        self.characters: dict[str, CharacterSpec] = {}
        if self.registry_file.exists():
            saved = json.loads(self.registry_file.read_text(encoding="utf-8"))
            for cid, data in saved.get("characters", {}).items():
                if cid in self.presets and not data.get("imported"):
                    # preset designs are the source of truth; keep only build bookkeeping
                    fresh = copy.deepcopy(self.presets[cid])
                    for k in ("asset", "asset_hash", "reference_image"):
                        if k in data:
                            fresh[k] = data[k]
                    data = fresh
                self.characters[cid] = CharacterSpec(cid, data)
        self._alias_index: dict[str, str] = {}
        self._reindex()

    def _reindex(self) -> None:
        self._alias_index.clear()
        for cid, data in self.presets.items():
            for a in [cid, data.get("name", "")] + data.get("aliases", []):
                if a:
                    self._alias_index[self._key(a)] = cid
        for cid, spec in self.characters.items():
            for a in [cid, spec.name] + spec.data.get("aliases", []):
                if a:
                    self._alias_index.setdefault(self._key(a), cid)

    @staticmethod
    def _key(name: str) -> str:
        return re.sub(r"\s+", " ", unicodedata.normalize("NFC", name).strip().lower())

    def resolve_id(self, name: str) -> str:
        """Map a speaker label ('Ustad Akram', 'لیو') to a character id."""
        key = self._key(name)
        if key in self._alias_index:
            return self._alias_index[key]
        stripped = re.sub(r"^(the|mr\.?|mrs\.?)\s+", "", key)
        if stripped in self._alias_index:
            return self._alias_index[stripped]
        return slugify(name)

    def get_or_create(self, name_or_id: str, context: str = "") -> CharacterSpec:
        cid = self.resolve_id(name_or_id)
        if cid in self.characters:
            return self.characters[cid]
        if cid in self.presets:
            data = copy.deepcopy(self.presets[cid])
        else:
            data = self._procedural_design(cid, name_or_id, context)
            log.info("Generated new procedural design for '%s' (%s)", name_or_id, cid)
        spec = CharacterSpec(cid, data)
        self.characters[cid] = spec
        self._reindex()
        return spec

    def _procedural_design(self, cid: str, name: str, context: str) -> dict:
        """Deterministic design for characters without a preset.

        Keywords from the script context (e.g. 'police', 'girl', 'old') steer the
        design; the name hash picks colours, so the same name is always identical.
        """
        r = _rng(cid)
        ctx = f"{name} {context}".lower()
        female = bool(re.search(r"\b(girl|woman|lady|mother|sister|aunt|she|her)\b|لڑکی|عورت|ماں|بہن|خالہ|باجی", ctx))
        child = bool(re.search(r"\b(child|kid|boy|girl|student)\b|بچہ|بچی|لڑکا|طالب", ctx))
        old = bool(re.search(r"\b(old|grand|elder)\b|بزرگ|دادا|نانا|دادی|نانی|بابا", ctx))
        police = bool(re.search(r"\b(police|officer|cop|inspector)\b|پولیس|انسپکٹر|سپاہی", ctx))
        villain = bool(re.search(r"\b(bully|villain|thief|robber|goon)\b|غنڈ|چور|ڈاکو|بدمعاش", ctx))
        shirt = r.choice(PALETTE)
        pants = r.choice([[0.2, 0.25, 0.45], [0.3, 0.25, 0.2], [0.15, 0.15, 0.18], [0.45, 0.4, 0.35]])
        accessories: list[str] = []
        if police:
            shirt, pants = [0.15, 0.25, 0.55], [0.1, 0.12, 0.25]
            accessories += ["police_cap", "belt"]
        hair_style = "long" if female else r.choice(["short", "spiky", "curly", "bowl"])
        if old:
            hair_style = "bald_sides"
        return {
            "name": name.strip() or cid,
            "aliases": [name.strip().lower()],
            "role": "villain" if villain else "neutral",
            "age_group": "child" if child else "adult",
            "gender": "female" if female else "male",
            "height": round((1.3 if child else 1.65 if female else 1.72) * r.uniform(0.96, 1.04), 3),
            "build": {"width": round(r.uniform(0.9, 1.15), 2), "belly": round(r.uniform(0.0, 0.2), 2)},
            "skin": r.choice(SKINS),
            "eye_color": r.choice([[0.2, 0.13, 0.07], [0.1, 0.35, 0.7], [0.2, 0.45, 0.25]]),
            "eye_size": 1.2 if child else 1.0,
            "hair": {"style": hair_style, "color": [0.75, 0.75, 0.78] if old else r.choice(HAIR)},
            "face": {"nose": r.choice(["button", "round", "pointy"]),
                     "moustache": (old or r.random() < 0.25) and not female and not child, "ears": True},
            "costume": {
                "shirt": shirt, "sleeves": shirt, "sleeve_length": r.choice(["short", "long"]),
                "pants": shirt if female else pants, "shoes": [0.15, 0.12, 0.1],
                "shoe_style": "sneakers", "gloves": None, "belt": [0.1, 0.1, 0.1] if police else None,
                "dress": female,
            },
            "accessories": accessories,
            "personality": "Generated from script context.",
            "voice": {"pitch": round((1.3 if (female or child) else 0.95) * r.uniform(0.94, 1.06), 3),
                      "rate": round(r.uniform(0.95, 1.05), 3), "style": "procedural"},
            "default_emotion": "neutral",
            "appearance": f"Procedural design for {name} from script context.",
            "procedural": True,
        }

    def group_members(self, group: str, among: list[str] | None = None) -> list[str]:
        members = [cid for cid, d in self.presets.items() if d.get("group") == group]
        members += [cid for cid, s in self.characters.items() if s.data.get("group") == group and cid not in members]
        return [m for m in members if among is None or m in among] or ([] if among is not None else members)

    def mentions(self, text: str, known: list[str] | None = None) -> list[str]:
        """Character ids named in free text, in order of first appearance."""
        return [cid for _, cid in self.mentions_with_pos(text, known)]

    def mentions_with_pos(self, text: str, known: list[str] | None = None) -> list[tuple[int, str]]:
        """(position, id) for characters named in text (English word-boundary or Urdu token match)."""
        best: dict[str, int] = {}
        low = unicodedata.normalize("NFC", text).lower()

        def find(alias: str) -> int:
            if re.search(r"[؀-ۿ]", alias):
                m = re.search(rf"(?<![؀-ۿ]){re.escape(alias)}(?![؀-ۿ])", low)
            else:
                m = re.search(rf"\b{re.escape(alias)}\b", low)
            return m.start() if m else -1

        for alias, cid in self._alias_index.items():
            if known is not None and cid not in known:
                continue
            if cid == "narrator" or alias in ("hero", "superhero", "bully"):
                continue
            pos = find(alias)
            if pos >= 0 and pos < best.get(cid, 1 << 30):
                best[cid] = pos
        for group, words in self.groups.items():
            positions = [p for p in (find(w) for w in words) if p >= 0]
            if positions:
                for cid in self.group_members(group, known):
                    if min(positions) < best.get(cid, 1 << 30):
                        best[cid] = min(positions)
        return sorted(((p, c) for c, p in best.items()), key=lambda pc: pc[0])

    def save(self) -> None:
        self.registry_file.parent.mkdir(parents=True, exist_ok=True)
        data = {"characters": {cid: s.data for cid, s in sorted(self.characters.items())}}
        self.registry_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def import_character(self, cid: str, data: dict) -> CharacterSpec:
        """Add or replace a character design (from the advanced editor or a JSON file)."""
        data = {**data, "imported": True}
        spec = CharacterSpec(cid, data)
        self.characters[cid] = spec
        self._reindex()
        self.save()
        return spec

    def asset_path(self, cid: str) -> Path:
        return CHARACTER_LIBRARY / f"{cid}.blend"

    def asset_is_current(self, cid: str) -> bool:
        spec = self.characters.get(cid)
        path = self.asset_path(cid)
        if spec is None or not path.exists():
            return False
        external = spec.data.get("external_asset")
        if external:
            return True
        return spec.data.get("asset_hash") == spec.design_hash()

    def mark_built(self, cid: str) -> None:
        spec = self.characters[cid]
        spec.data["asset_hash"] = spec.design_hash()
        spec.data["asset"] = str(self.asset_path(cid))
        spec.data["reference_image"] = str(CHARACTER_LIBRARY / f"{cid}_reference.png")
