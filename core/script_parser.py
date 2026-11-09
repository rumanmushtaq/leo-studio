"""Lexical script parser: turns a free-form Urdu/English cartoon script into
ordered scenes and events (visual, dialogue, narration, sfx, camera, transition).

The parser never rewrites dialogue text. Lines it cannot classify are kept as
visual descriptions and reported as warnings, so nothing the user wrote is lost.
Semantic enrichment (locations, actions, emotions) lives in ``scene_manager``.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field

URDU_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
ARABIC_SCRIPT = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")

HEADING_EN = re.compile(r"^\s*(?:scene|sc\.)\s*(?:no\.?|#)?\s*([0-9]+)?\s*[:\-–—.)]*\s*(.*)$", re.I)
HEADING_UR = re.compile(r"^\s*(?:سین|منظر|مَنظر)\s*(?:نمبر)?\s*([0-9]+)\s*[:\-–—.)۔]*\s*(.*)$")
HEADING_SLUG = re.compile(r"^\s*(INT\.|EXT\.|INT/EXT\.)\s*(.*)$", re.I)
LABEL = re.compile(r"^\s*([^:：\n]{1,40}?)\s*(?:[(\[]([^)\]]{1,30})[)\]])?\s*[:：]\s*(.*)$")
BRACKET_SFX = re.compile(r"^\s*[\[(]\s*(?:sfx|sound|sound effect|آواز)?\s*[:：]?\s*([^\])]+)[\])]\s*$", re.I)
PAREN_ONLY = re.compile(r"^\s*\(([^)]{1,30})\)\s*$")

RESERVED_LABELS: dict[str, str] = {}
for _kind, _words in {
    "visual": ["visual", "visuals", "description", "action", "scene description", "setting", "بیان", "منظر", "منظرنامہ", "ایکشن"],
    "narration": ["narrator", "narration", "voice over", "voiceover", "v.o.", "راوی", "بیانیہ", "کہانی کار"],
    "sfx": ["sfx", "sound", "sound effect", "sound effects", "آواز", "صوتی اثر"],
    "music": ["music", "bgm", "موسیقی"],
    "camera": ["camera", "shot", "کیمرہ"],
    "transition": ["transition", "cut to", "fade", "fade to", "ٹرانزیشن"],
    "location": ["location", "place", "مقام", "جگہ"],
}.items():
    for _w in _words:
        RESERVED_LABELS[_w] = _kind


@dataclass
class Event:
    """One ordered element of a scene."""

    kind: str  # visual | dialogue | narration | sfx | music | camera | transition | location
    text: str
    speaker: str | None = None  # raw speaker label for dialogue
    speaker_id: str | None = None
    emotion_hint: str | None = None
    line_no: int = 0
    # Filled by scene_manager:
    emotion: str | None = None
    actions: list[dict] = field(default_factory=list)
    language: str = "en"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ParsedScene:
    id: int
    title: str
    heading_line: int = 0
    events: list[Event] = field(default_factory=list)
    inferred: bool = False
    # Filled by scene_manager:
    location: str = ""
    characters: list[str] = field(default_factory=list)
    visual_description: str = ""
    estimated_duration: float = 0.0
    transition_in: str = "dissolve"
    camera_hints: list[str] = field(default_factory=list)
    sound_effects: list[str] = field(default_factory=list)

    @property
    def dialogues(self) -> list[Event]:
        return [e for e in self.events if e.kind in ("dialogue", "narration")]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["dialogues"] = [
            {"character": e.speaker_id or "narrator", "text": e.text, "emotion": e.emotion,
             "kind": e.kind, "language": e.language}
            for e in self.dialogues
        ]
        return d


@dataclass
class ParseReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass
class ParsedScript:
    scenes: list[ParsedScene]
    report: ParseReport
    source_text: str = ""

    def all_dialogue_events(self) -> list[Event]:
        return [e for s in self.scenes for e in s.dialogues]

    def to_dict(self) -> dict:
        return {
            "scenes": [s.to_dict() for s in self.scenes],
            "report": asdict(self.report),
        }


def detect_language(text: str) -> str:
    """'ur' if the text is mostly Arabic-script, else 'en'."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return "en"
    ar = sum(1 for c in letters if ARABIC_SCRIPT.match(c))
    return "ur" if ar / len(letters) > 0.4 else "en"


def normalize_label(label: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", label)).strip().strip("*#-_").strip().lower()


def _heading(line: str) -> tuple[bool, int | None, str]:
    norm = line.translate(URDU_DIGITS)
    m = HEADING_UR.match(norm)
    if m:
        return True, int(m.group(1)), m.group(2).strip()
    m = HEADING_EN.match(norm)
    if m and (m.group(1) or norm.strip().lower().startswith("scene")):
        title = m.group(2).strip()
        # "Scene description: ..." is a visual label, not a heading.
        if not m.group(1) and re.match(r"^\s*scene\s+description", norm, re.I):
            return False, None, ""
        return True, int(m.group(1)) if m.group(1) else None, title
    m = HEADING_SLUG.match(norm)
    if m:
        return True, None, m.group(2).strip(" .-")
    return False, None, ""


def _is_plausible_label(label: str) -> bool:
    """Speaker labels are short names, not sentences."""
    words = label.split()
    if not words or len(words) > 4:
        return False
    if re.search(r"[.!?؟۔،,]", label):
        return False
    return True


class ScriptParser:
    """Parse script text into :class:`ParsedScript`."""

    def parse(self, text: str) -> ParsedScript:
        report = ParseReport()
        text = unicodedata.normalize("NFC", text or "").replace("\r\n", "\n").replace("\r", "\n")
        if not text.strip():
            report.errors.append("Script is empty. Paste a cartoon script with scenes and dialogue.")
            return ParsedScript([], report, text)

        scenes: list[ParsedScene] = []
        current: ParsedScene | None = None
        block: Event | None = None  # event whose text continues on following lines
        pending_emotion: str | None = None
        had_heading = False

        def ensure_scene(line_no: int) -> ParsedScene:
            nonlocal current
            if current is None:
                current = ParsedScene(id=len(scenes) + 1, title="", heading_line=line_no, inferred=True)
                scenes.append(current)
            return current

        for line_no, raw in enumerate(text.split("\n"), start=1):
            line = raw.strip().strip("‏‎")
            if not line:
                block = None
                continue

            is_heading, number, title = _heading(line)
            if is_heading:
                had_heading = True
                current = ParsedScene(id=len(scenes) + 1, title=title, heading_line=line_no)
                scenes.append(current)
                block = None
                pending_emotion = None
                continue

            m = BRACKET_SFX.match(line)
            if m and (line.lstrip().startswith("[") or re.match(r"^\s*\(\s*(sfx|sound|آواز)", line, re.I)):
                ensure_scene(line_no).events.append(Event("sfx", m.group(1).strip(), line_no=line_no))
                block = None
                continue

            m = PAREN_ONLY.match(line)
            if m:
                pending_emotion = m.group(1).strip().lower()
                if block is not None and block.kind in ("dialogue", "narration") and not block.text:
                    block.emotion_hint = pending_emotion
                    pending_emotion = None
                continue

            m = LABEL.match(line)
            if m and _is_plausible_label(m.group(1)):
                label, paren, rest = m.group(1).strip(), m.group(2), m.group(3).strip()
                key = normalize_label(label)
                kind = RESERVED_LABELS.get(key)
                scene = ensure_scene(line_no)
                if kind is None and key.startswith(("cut to", "fade")):
                    kind = "transition"
                if kind is None:
                    ev = Event("dialogue", rest, speaker=label, line_no=line_no,
                               emotion_hint=(paren.strip().lower() if paren else pending_emotion))
                elif kind == "narration":
                    ev = Event("narration", rest, speaker="Narrator", speaker_id="narrator", line_no=line_no,
                               emotion_hint=(paren.strip().lower() if paren else pending_emotion))
                else:
                    ev = Event(kind, rest, line_no=line_no)
                pending_emotion = None
                scene.events.append(ev)
                block = ev
                continue

            # Plain line: continues the open block, else becomes a visual description.
            scene = ensure_scene(line_no)
            if block is not None:
                block.text = (block.text + "\n" + line).strip() if block.text else line
                continue
            if re.match(r"^\s*(cut to|fade (in|out|to)|dissolve)", line, re.I):
                scene.events.append(Event("transition", line, line_no=line_no))
                continue
            ev = Event("visual", line, line_no=line_no)
            scene.events.append(ev)
            block = ev
            report.warnings.append(f"Line {line_no}: unlabeled text kept as visual description: {line[:60]}")

        # Drop dialogue blocks that never received text, but report them.
        for s in scenes:
            kept = []
            for e in s.events:
                if e.kind in ("dialogue", "narration") and not e.text.strip():
                    report.warnings.append(f"Line {e.line_no}: '{e.speaker}' has no dialogue text; skipped.")
                    continue
                e.language = detect_language(e.text)
                kept.append(e)
            s.events = kept

        scenes = [s for s in scenes if s.events]
        for i, s in enumerate(scenes, start=1):
            s.id = i

        if not had_heading and scenes:
            report.warnings.append("No scene headings found; scenes were inferred from the script structure.")
        if not any(e.kind in ("dialogue", "narration") for s in scenes for e in s.events):
            report.errors.append("No dialogue or narration found. Use 'Name: text' lines, e.g. 'Leo: ...'.")
        for s in scenes:
            if not s.dialogues:
                report.warnings.append(f"Scene {s.id} '{s.title}' has no dialogue or narration.")
        return ParsedScript(scenes, report, text)
