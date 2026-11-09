"""Load ComfyUI workflow templates and fill their {{PLACEHOLDER}} values."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from utils.config import ASSETS_DIR

WORKFLOW_DIR = ASSETS_DIR / "comfy_workflows"
TEMPLATES = {"restyle": "restyle_flux.json", "i2v": "image_to_video_wan22.json", "lipsync": "lipsync_latentsync.json"}


def load(name: str, directory: Path = WORKFLOW_DIR) -> dict:
    data = json.loads((Path(directory) / TEMPLATES.get(name, name)).read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def fill(workflow: dict, **values) -> dict:
    """Replace string values that are exactly "{{KEY}}" with ``values[KEY]`` (keeping its type)."""
    wf = copy.deepcopy(workflow)
    missing: set[str] = set()

    def walk(obj):
        if isinstance(obj, dict):
            return {k: walk(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [walk(v) for v in obj]
        if isinstance(obj, str) and obj.startswith("{{") and obj.endswith("}}"):
            key = obj[2:-2]
            if key not in values:
                missing.add(key)
                return obj
            return values[key]
        return obj

    wf = walk(wf)
    if missing:
        raise KeyError(f"Workflow placeholders without values: {sorted(missing)}")
    return wf
