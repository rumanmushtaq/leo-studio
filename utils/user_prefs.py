"""Small per-user preferences file (simple/studio mode, measured render speed)."""
from __future__ import annotations

import json

from utils.config import PROJECT_ROOT

PREFS_FILE = PROJECT_ROOT / "user_settings.json"
DEFAULT_SPF = {"preview": 0.8, "standard": 3.5, "high": 9.0}  # seconds per frame on a laptop iGPU


def load() -> dict:
    try:
        return json.loads(PREFS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(**values) -> None:
    data = load()
    data.update(values)
    try:
        PREFS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


def record_render_speed(quality: str, seconds_per_frame: float) -> None:
    """Remember how fast this PC rendered, so the next time estimate is realistic."""
    speeds = load().get("seconds_per_frame", {})
    old = speeds.get(quality)
    speeds[quality] = round(seconds_per_frame if old is None else 0.5 * old + 0.5 * seconds_per_frame, 3)
    save(seconds_per_frame=speeds)


def seconds_per_frame(quality: str) -> float:
    return float(load().get("seconds_per_frame", {}).get(quality, DEFAULT_SPF.get(quality, 3.5)))


def estimate_minutes(video_seconds: float, quality: str, lines: int = 20, new_characters: int = 0) -> int:
    frames = video_seconds * 24
    total = frames * seconds_per_frame(quality) + lines * 4 + new_characters * 60 + 120 + video_seconds * 1.5
    return max(1, round(total / 60))


def human_duration(minutes: int) -> str:
    if minutes < 60:
        return f"about {minutes} minutes"
    h, m = divmod(minutes, 60)
    return f"about {h} hour{'s' if h > 1 else ''}" + (f" {m} minutes" if m >= 10 else "")
