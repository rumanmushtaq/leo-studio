"""YouTube thumbnail: a video frame with a big outlined title (Urdu shaped right-to-left)."""
from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from core.script_parser import detect_language
from utils import text_shaping as ts
from utils.config import PROC_KW, find_ffmpeg

SIZE = (1280, 720)  # YouTube's recommended thumbnail size (16:9, under 2 MB as JPEG)


def grab_frame(video: Path, seconds: float, out: Path) -> Path:
    ff = find_ffmpeg()
    if not ff:
        raise RuntimeError("FFmpeg was not found.")
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([ff, "-y", "-loglevel", "error", "-ss", f"{max(0.0, seconds):.2f}", "-i", str(video),
                    "-frames:v", "1", str(out)], check=True, capture_output=True, timeout=60, **PROC_KW)
    return out


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, kw: dict, lang: str, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        shown, _ = ts.prepare(trial, lang)
        if draw.textlength(shown, font=font, **kw) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines[:3]


def make_thumbnail(frame: Path | Image.Image, title: str, out: Path, colour: str = "#ffd23f",
                   position: str = "bottom") -> Path:
    img = frame.copy() if isinstance(frame, Image.Image) else Image.open(frame)
    img = img.convert("RGB").resize(SIZE, Image.LANCZOS)
    img = ImageEnhance.Color(img).enhance(1.25)
    img = ImageEnhance.Contrast(img).enhance(1.08)
    title = " ".join(title.split())
    if title:
        lang = detect_language(title)
        # dark gradient behind the text so it reads on any frame
        shade = Image.new("L", SIZE, 0)
        sd = ImageDraw.Draw(shade)
        top = position == "top"
        for y in range(SIZE[1]):
            t = (1 - y / (SIZE[1] * 0.55)) if top else (y - SIZE[1] * 0.45) / (SIZE[1] * 0.55)
            sd.line([(0, y), (SIZE[0], y)], fill=int(200 * max(0.0, min(1.0, t))))
        img = Image.composite(Image.new("RGB", SIZE, (8, 10, 24)), img, shade.filter(ImageFilter.GaussianBlur(8)))
        d = ImageDraw.Draw(img)
        size = 96 if len(title) < 28 else 78 if len(title) < 48 else 62
        font = ts.font(lang, size)
        _, kw = ts.prepare(title, lang)
        lines = _wrap(d, title, font, kw, lang, SIZE[0] - 120)
        line_h = int(size * ts.line_height_factor(lang))
        block = line_h * len(lines)
        y = 40 if top else SIZE[1] - block - 40
        for line in lines:
            shown, kw = ts.prepare(line, lang)
            bbox = d.textbbox((0, 0), shown, font=font, **kw)
            w = bbox[2] - bbox[0]
            x = (SIZE[0] - w) // 2 - bbox[0]
            ty = y + (line_h - (bbox[3] - bbox[1])) // 2 - bbox[1]
            d.text((x, ty), shown, font=font, fill=colour, stroke_width=max(4, size // 14), stroke_fill="#101018",
                   **kw)
            y += line_h
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "JPEG", quality=90, optimize=True)
    return out
