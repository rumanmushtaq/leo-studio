"""Cross-platform Urdu/Arabic text drawing with Pillow.

Preferred: Pillow's libraqm layout (HarfBuzz shaping + FriBiDi reordering) with
Noto Nastaliq Urdu — true Nastaliq calligraphy. Pillow wheels on Windows often
ship raqm without FriBiDi, in which case raqm is unavailable; then text is
shaped by ``arabic_reshaper`` (contextual letter forms) and reordered by
``python-bidi`` and drawn with Noto Naskh Arabic, whose presentation-form
glyphs render correctly without HarfBuzz. Both paths keep the original text
unchanged in the SRT; only the drawing differs.
"""
from __future__ import annotations

from functools import lru_cache

from PIL import ImageFont, features

from utils.config import FONT_DIR, LATIN_FONT_CANDIDATES, URDU_FONT_CANDIDATES, find_font

NASKH_CANDIDATES = [str(FONT_DIR / "NotoNaskhArabic-Regular.ttf"),
                    "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
                    r"C:\Windows\Fonts\NotoNaskhArabic-Regular.ttf", r"C:\Windows\Fonts\arial.ttf"]


@lru_cache(maxsize=1)
def raqm_available() -> bool:
    try:
        return bool(features.check("raqm"))
    except Exception:
        return False


def shaping_backend() -> str:
    return "raqm (HarfBuzz + FriBiDi)" if raqm_available() else "arabic-reshaper + python-bidi"


@lru_cache(maxsize=32)
def font(lang: str, size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    if lang == "ur":
        if raqm_available():
            return ImageFont.truetype(find_font(URDU_FONT_CANDIDATES), size, layout_engine=ImageFont.Layout.RAQM)
        return ImageFont.truetype(find_font(NASKH_CANDIDATES), size, layout_engine=ImageFont.Layout.BASIC)
    layout = ImageFont.Layout.RAQM if raqm_available() else ImageFont.Layout.BASIC
    return ImageFont.truetype(find_font(LATIN_FONT_CANDIDATES), size, layout_engine=layout)


def prepare(text: str, lang: str) -> tuple[str, dict]:
    """Text to hand to ImageDraw.text plus keyword arguments for it."""
    if lang != "ur":
        return text, {}
    if raqm_available():
        return text, {"direction": "rtl", "language": "ur"}
    import arabic_reshaper
    from bidi import get_display

    return get_display(arabic_reshaper.reshape(text)), {}


def line_height_factor(lang: str) -> float:
    """Nastaliq needs much more vertical room than Naskh or Latin."""
    if lang != "ur":
        return 1.35
    return 2.0 if raqm_available() else 1.6
