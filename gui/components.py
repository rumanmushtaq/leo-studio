"""Reusable CustomTkinter widgets."""
from __future__ import annotations

import customtkinter as ctk
from PIL import Image, ImageDraw

from core.script_parser import detect_language
from utils import text_shaping as ts

ACCENT = "#3b82f6"
ACCENT_HOVER = "#2563eb"
DANGER = "#ef4444"
CARD = "#1b2130"
CARD_BORDER = "#2a3244"
MUTED = "#94a3b8"


class Card(ctk.CTkFrame):
    def __init__(self, master, **kw):
        super().__init__(master, fg_color=CARD, corner_radius=14, border_width=1, border_color=CARD_BORDER, **kw)


class SectionTitle(ctk.CTkLabel):
    def __init__(self, master, text: str, **kw):
        super().__init__(master, text=text, font=ctk.CTkFont(size=14, weight="bold"), anchor="w", **kw)


class UrduPreview(ctk.CTkLabel):
    """Correctly shaped right-to-left preview of one script line.

    Tk's text widget does not apply Arabic-script shaping or bidi reordering on
    every platform, so the line under the cursor is rendered with Pillow
    (the same shaping used for the video subtitles) to show the true result.
    """

    def __init__(self, master, width: int = 760, height: int = 64, **kw):
        super().__init__(master, text="", width=width, height=height, **kw)
        self.w, self.h = width, height
        self._img = None

    def show(self, line: str) -> None:
        img = Image.new("RGB", (self.w * 2, self.h * 2), "#111827")
        d = ImageDraw.Draw(img)
        line = line.strip()
        if line:
            lang = detect_language(line)
            font = ts.font(lang, 40 if lang == "ur" else 34)
            text, kw = ts.prepare(line, lang)
            bbox = d.textbbox((0, 0), text, font=font, **kw)
            tw = bbox[2] - bbox[0]
            x = (self.w * 2 - 24 - tw) if lang == "ur" else 24
            y = (self.h * 2 - (bbox[3] - bbox[1])) // 2 - bbox[1]
            d.text((x - bbox[0], y), text, font=font, fill="#f8fafc", **kw)
        else:
            d.text((24, self.h - 12), "Line preview (Urdu shown right-to-left with proper shaping)", fill="#64748b")
        self._img = ctk.CTkImage(light_image=img, dark_image=img, size=(self.w, self.h))
        self.configure(image=self._img)


def render_script_image(text: str, width: int = 1400) -> Image.Image:
    """Whole script as an image with correct Urdu shaping and right-to-left lines."""
    rows = []
    for line in text.splitlines()[:2000]:
        lang = detect_language(line) if line.strip() else "en"
        rows.append((line, lang, int(34 * ts.line_height_factor(lang)) if lang == "ur" else 40))
    img = Image.new("RGB", (width, max(80, sum(h for _, _, h in rows) + 40)), "#0b1220")
    d = ImageDraw.Draw(img)
    y = 20
    for line, lang, h in rows:
        if line.strip():
            font = ts.font(lang, 34 if lang == "ur" else 26)
            shown, kw = ts.prepare(line, lang)
            bbox = d.textbbox((0, 0), shown, font=font, **kw)
            x = (width - 30 - (bbox[2] - bbox[0]) - bbox[0]) if lang == "ur" else 30
            label = line.rstrip().endswith(":") or line.lower().startswith(("scene", "visual"))
            d.text((x, y + (h - (bbox[3] - bbox[1])) // 2 - bbox[1]), shown, font=font,
                   fill="#7dd3fc" if label else "#f1f5f9", **kw)
        y += h
    return img
