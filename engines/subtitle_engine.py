"""Subtitles: SRT export and burned-in subtitle images.

Text comes verbatim from the script. Urdu is shaped and laid out right-to-left
by Pillow's libraqm layout engine (HarfBuzz + FriBiDi) with Noto Nastaliq Urdu,
rendered to transparent PNGs, and overlaid by FFmpeg at the exact dialogue
times. Pre-rendering avoids depending on libass shaping support in FFmpeg.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from core.script_parser import detect_language
from utils import text_shaping as ts
from utils.config import LATIN_FONT_CANDIDATES, OUTPUT_HEIGHT, OUTPUT_WIDTH, URDU_FONT_CANDIDATES, find_font


@dataclass
class Cue:
    index: int
    start: float
    end: float
    text: str
    speaker: str
    language: str
    image: Path | None = None


def _ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


class SubtitleEngine:
    def __init__(self, width: int = OUTPUT_WIDTH, height: int = OUTPUT_HEIGHT):
        self.width = width
        self.height = height
        if not find_font(URDU_FONT_CANDIDATES) or not find_font(LATIN_FONT_CANDIDATES):
            raise RuntimeError("Subtitle fonts missing: assets/fonts/ should contain the bundled Noto fonts.")
        self.backend = ts.shaping_backend()

    def cues(self, timeline: dict, names: dict[str, str]) -> list[Cue]:
        out: list[Cue] = []
        fps = timeline["fps"]
        all_lines = []
        for sd in timeline["scenes"]:
            for d in sd["dialogues"]:
                all_lines.append((sd["start_time"] + d["start"] / fps, sd["start_time"] + d["end"] / fps, d))
        for i, (s, e, d) in enumerate(all_lines):
            nxt = all_lines[i + 1][0] if i + 1 < len(all_lines) else e + 1.0
            end = min(e + 0.35, nxt - 0.04)
            speaker = names.get(d["speaker"], d["speaker"].replace("_", " ").title())
            out.append(Cue(i + 1, round(s, 3), round(max(end, s + 0.5), 3), d["text"], speaker,
                           d.get("language") or detect_language(d["text"])))
        return out

    @staticmethod
    def write_srt(cues: list[Cue], path: Path) -> None:
        lines = []
        for c in cues:
            lines += [str(c.index), f"{_ts(c.start)} --> {_ts(c.end)}", c.text.strip(), ""]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines), encoding="utf-8")

    @staticmethod
    def _wrap(text: str, font, lang: str, max_w: int) -> list[str]:
        """Word-wrap in logical (reading) order; each line is shaped separately."""
        lines: list[str] = []
        for para in text.split("\n"):
            words, cur = para.split(), ""
            for w in words:
                trial = (cur + " " + w).strip()
                shaped, kw = ts.prepare(trial, lang)
                if font.getlength(shaped, **kw) <= max_w or not cur:
                    cur = trial
                else:
                    lines.append(cur)
                    cur = w
            if cur:
                lines.append(cur)
        return lines

    def render(self, cue: Cue, path: Path) -> Path:
        """Transparent full-frame PNG with the subtitle box near the bottom."""
        lang = cue.language
        size = 40 if lang == "ur" else 36
        font = ts.font(lang, size)
        name_font = ts.font("en", 24)
        lines = [ts.prepare(line, lang) for line in self._wrap(cue.text, font, lang, int(self.width * 0.8))]
        boxes = [font.getbbox(text, **kw) for text, kw in lines]
        line_h = int(size * ts.line_height_factor(lang))
        text_w = max(b[2] - b[0] for b in boxes)
        pad_x, pad_y = 28, 14
        box_w = text_w + 2 * pad_x
        box_h = line_h * len(lines) + 2 * pad_y
        img = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        x0 = (self.width - box_w) // 2
        y0 = self.height - box_h - 34
        d.rounded_rectangle((x0, y0, x0 + box_w, y0 + box_h), radius=18, fill=(10, 12, 24, 170))
        is_narr = cue.speaker.lower() == "narrator"
        tag = cue.speaker
        tag_w = name_font.getlength(tag) + 24
        tag_color = (120, 200, 255, 235) if not is_narr else (255, 214, 102, 235)
        d.rounded_rectangle((x0 + 12, y0 - 30, x0 + 12 + tag_w, y0 + 4), radius=10, fill=tag_color)
        d.text((x0 + 24, y0 - 28), tag, font=name_font, fill=(10, 12, 24, 255))
        for i, (line, kw) in enumerate(lines):
            b = boxes[i]
            w = b[2] - b[0]
            x = (self.width - w) // 2 - b[0]
            y = y0 + pad_y + i * line_h + (line_h - (b[3] - b[1])) // 2 - b[1]
            fill = (255, 245, 210, 255) if is_narr else (255, 255, 255, 255)
            d.text((x, y), line, font=font, fill=fill, stroke_width=2, stroke_fill=(0, 0, 0, 255), **kw)
        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(path)
        cue.image = path
        return path

    def render_all(self, cues: list[Cue], out_dir: Path) -> list[Cue]:
        for c in cues:
            self.render(c, out_dir / f"sub_{c.index:03d}.png")
        return cues
