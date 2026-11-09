"""Central configuration: paths, render quality presets and tool discovery."""
from __future__ import annotations

import glob
import os
import platform
import shutil
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets"
CHARACTER_LIBRARY = ASSETS_DIR / "characters"
ANIMATION_LIBRARY = ASSETS_DIR / "animations"
ENVIRONMENT_LIBRARY = ASSETS_DIR / "environments"
SOUND_LIBRARY = ASSETS_DIR / "sounds"
FONT_DIR = ASSETS_DIR / "fonts"
TEMP_DIR = PROJECT_ROOT / "temp"
OUTPUT_DIR = PROJECT_ROOT / "output"
MODEL_CACHE = PROJECT_ROOT / "models" / "cache"

FPS = 24
OUTPUT_WIDTH = 1280
OUTPUT_HEIGHT = 720
MIN_VIDEO_SECONDS = 60.0
AUDIO_SAMPLE_RATE = 44100
TRANSITION_SECONDS = 0.5


@dataclass(frozen=True)
class RenderPreset:
    """Blender render settings for one quality level.

    ``resolution_percentage`` scales the 1280x720 base. Lower values render
    faster; FFmpeg scales the result back to 1280x720 in the final MP4.
    """

    name: str
    resolution_percentage: int
    taa_samples: int
    shadows: bool
    outline: bool
    jpeg_quality: int


RENDER_PRESETS: dict[str, RenderPreset] = {
    "preview": RenderPreset("preview", 50, 1, False, True, 85),
    "standard": RenderPreset("standard", 100, 4, True, True, 92),
    "high": RenderPreset("high", 100, 16, True, True, 95),
}


# Child processes (Blender, FFmpeg): decode their output as UTF-8 on every OS, and on
# Windows do not pop up a console window for each one when running the GUI.
PROC_KW: dict = {"encoding": "utf-8", "errors": "replace"}
if platform.system() == "Windows":
    import subprocess as _sp

    PROC_KW["creationflags"] = getattr(_sp, "CREATE_NO_WINDOW", 0)


def _first_existing(candidates: list[str]) -> str | None:
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def find_blender() -> str | None:
    """Locate a Blender executable. ``LEO_BLENDER`` env var wins."""
    env = os.environ.get("LEO_BLENDER")
    if env and os.path.isfile(env):
        return env
    on_path = shutil.which("blender")
    candidates: list[str] = [on_path] if on_path else []
    home = Path.home()
    patterns = [
        str(home / "opt" / "blender-4.*" / "blender"),
        str(home / "blender-4.*" / "blender"),
        str(PROJECT_ROOT / "tools" / "blender-4.*" / "blender"),
        "/opt/blender*/blender",
        "/snap/bin/blender",
    ]
    if platform.system() == "Windows":
        for root in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("LOCALAPPDATA", "")):
            if root:
                patterns += [os.path.join(root, "Blender Foundation", "Blender 4.*", "blender.exe"),
                             os.path.join(root, "Programs", "Blender Foundation", "Blender 4.*", "blender.exe")]
        patterns += [str(home / "opt" / "blender-4.*" / "blender.exe"),
                     str(PROJECT_ROOT / "tools" / "blender-4.*" / "blender.exe")]
    elif platform.system() == "Darwin":
        patterns += ["/Applications/Blender.app/Contents/MacOS/Blender"]
    for p in patterns:
        candidates += sorted(glob.glob(p), reverse=True)
    return _first_existing(candidates)


def find_ffmpeg() -> str | None:
    """System FFmpeg first; otherwise the static build shipped by the imageio-ffmpeg wheel
    (Windows, macOS and Linux), so a fresh `pip install` is enough on every platform."""
    env = os.environ.get("LEO_FFMPEG")
    if env and os.path.isfile(env):
        return env
    found = shutil.which("ffmpeg")
    if found:
        return found
    if platform.system() == "Windows":
        for c in (r"C:\ffmpeg\bin\ffmpeg.exe", os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links\ffmpeg.exe"),
                  r"C:\ProgramData\chocolatey\bin\ffmpeg.exe"):
            if os.path.isfile(c):
                return c
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def find_ffprobe() -> str | None:
    env = os.environ.get("LEO_FFPROBE")
    if env and os.path.isfile(env):
        return env
    found = shutil.which("ffprobe")
    if found:
        return found
    ff = find_ffmpeg()
    if ff:
        sibling = Path(ff).with_name("ffprobe" + (".exe" if ff.endswith(".exe") else ""))
        if sibling.is_file():
            return str(sibling)
    return None


URDU_FONT_CANDIDATES = [
    str(FONT_DIR / "NotoNastaliqUrdu-Regular.ttf"),
    "/usr/share/fonts/truetype/noto/NotoNastaliqUrdu-Regular.ttf",
    "/usr/share/fonts/opentype/noto/NotoNastaliqUrdu-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
    r"C:\Windows\Fonts\NotoNastaliqUrdu-Regular.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
]
LATIN_FONT_CANDIDATES = [
    str(FONT_DIR / "NotoSans-Bold.ttf"),
    str(FONT_DIR / "NotoSans-Regular.ttf"),
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
]


def find_font(candidates: list[str]) -> str | None:
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


@dataclass
class GenerationSettings:
    """User-facing options for one generation run."""

    output_dir: Path = field(default_factory=lambda: OUTPUT_DIR)
    quality: str = "standard"
    episode_name: str | None = None
    use_gpu: bool = False
    voice_backend: str = "auto"  # auto | mms | espeak | manual
    manual_audio_dir: Path | None = None
    music: bool = True
    keep_temp: bool = False
    render_engine: str = "blender"  # blender | ai (ComfyUI server: Flux restyle + Wan 2.2 + LatentSync)
    comfy_url: str = "http://127.0.0.1:8188"
    ai_lipsync: bool = True
    ai_backgrounds: bool = True  # paint backdrops with the free CPU model when it is installed

    @property
    def preset(self) -> RenderPreset:
        return RENDER_PRESETS.get(self.quality, RENDER_PRESETS["standard"])
