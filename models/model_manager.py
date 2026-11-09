"""Inventory of optional AI models: what exists locally, sizes and licenses.

Nothing is downloaded silently: the GUI shows this list and the voice engine
only downloads MMS-TTS (about 145 MB per language) when generation runs with
the "auto"/"mms" voice backend and the user has internet access.
"""
from __future__ import annotations

from dataclasses import dataclass

from engines.voice_engine import MMS_MODELS, MMSBackend


@dataclass(frozen=True)
class ModelInfo:
    key: str
    repo: str
    purpose: str
    size_mb: int
    license: str
    commercial_use: bool
    runs_on_cpu: bool
    integrated: bool
    note: str


MODELS = [
    ModelInfo("mms_tts_urdu", MMS_MODELS["ur"], "Urdu text-to-speech (VITS)", 145, "CC-BY-NC-4.0", False, True,
              True, "Default Urdu voice. Non-commercial license: commercial users must replace it."),
    ModelInfo("mms_tts_english", MMS_MODELS["en"], "English text-to-speech (VITS)", 145, "CC-BY-NC-4.0", False,
              True, True, "Used for English dialogue lines."),
    ModelInfo("espeak_ng", "espeakng-loader (PyPI)", "Fallback Urdu/English TTS (formant synthesis)", 20,
              "GPL-3.0", True, True, True, "Always offline; robotic voice quality."),
    ModelInfo("stable_fast_3d", "stabilityai/stable-fast-3d", "Image-to-3D asset generation (investigated)",
              4000, "Stability AI Community License (free < $1M revenue)", True, False, False,
              "Needs a CUDA GPU with ~6 GB VRAM; not integrated. Procedural Blender modelling is used instead."),
]


def model_status() -> list[dict]:
    out = []
    for m in MODELS:
        downloaded = None
        if m.key == "mms_tts_urdu":
            downloaded = MMSBackend.is_downloaded("ur")
        elif m.key == "mms_tts_english":
            downloaded = MMSBackend.is_downloaded("en")
        elif m.key == "espeak_ng":
            try:
                import espeakng_loader  # noqa: F401

                downloaded = True
            except ImportError:
                downloaded = False
        out.append({**m.__dict__, "downloaded": downloaded})
    return out
