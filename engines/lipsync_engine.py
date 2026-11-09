"""Lip-sync curves for the face shape keys.

Two levels, chosen automatically per dialogue line:

1. **Letter (phoneme) level** - when the line was voiced by MMS-TTS the voice engine saves how long
   every letter was spoken (taken from the model's own duration predictor). Each Urdu/English letter
   maps to a mouth shape (viseme): open "aa", wide "ee", round "oo", closed lips "m/b/p", lip-to-teeth
   "f/v", or a small neutral opening for other consonants. Shapes cross-fade between letters
   (coarticulation) and are scaled by the audio loudness so silences close the mouth.
2. **Loudness level** - for eSpeak or recorded audio (no letter timing): mouth opening follows the
   RMS loudness and the spectral centroid splits it into wide vs. round shapes.

Outputs per video frame: open, wide, round, mbp, fv in 0..1.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from utils.audio_utils import frame_envelope, frame_spectral_centroid, read_audio
from utils.config import AUDIO_SAMPLE_RATE, FPS

# viseme -> (open, wide, round, mbp, fv)
VISEMES = {
    "A": (1.0, 0.2, 0.0, 0.0, 0.0),    # aa
    "E": (0.45, 0.9, 0.0, 0.0, 0.0),   # ee / i
    "O": (0.55, 0.0, 1.0, 0.0, 0.0),   # oo / o / w
    "M": (0.0, 0.0, 0.0, 1.0, 0.0),    # m b p (lips pressed)
    "F": (0.15, 0.2, 0.0, 0.0, 1.0),   # f v (lower lip to teeth)
    "C": (0.35, 0.35, 0.0, 0.0, 0.0),  # other consonants (t d s n l r k ...)
    "X": (0.0, 0.0, 0.0, 0.0, 0.0),    # rest / pause
}
LETTER_VISEME: dict[str, str] = {}
for _chars, _v in (("اآأإعہھحخغقکگءه", "A"), ("یےئيِ", "E"), ("وؤُ", "O"), ("بپم", "M"), ("ف", "F"),
                   ("تٹدڈنںلرڑسشزژصضطظجچذثة", "C"),
                   ("ah", "A"), ("eiy", "E"), ("ouw", "O"), ("bmp", "M"), ("fv", "F"),
                   ("cdgjklnqrstxz", "C")):
    for _c in _chars:
        LETTER_VISEME[_c] = _v


def lipsync_curves(audio_path: Path, fps: int = FPS) -> dict[str, list[float]]:
    data = read_audio(audio_path, AUDIO_SAMPLE_RATE)
    letters = Path(audio_path).with_suffix(".letters.json")
    if letters.exists():
        timing = json.loads(letters.read_text(encoding="utf-8"))
        return lipsync_from_letters(timing, data, AUDIO_SAMPLE_RATE, fps)
    return lipsync_from_array(data, AUDIO_SAMPLE_RATE, fps)


def _envelope01(data: np.ndarray, sr: int, fps: int) -> np.ndarray:
    env = frame_envelope(data, sr, fps)
    if len(env) == 0:
        return env
    floor, peak = float(np.percentile(env, 15)), float(np.percentile(env, 95))
    return np.clip((env - floor) / max(peak - floor, 1e-5), 0.0, 1.0)


def lipsync_from_letters(timing: list, data: np.ndarray, sr: int, fps: int = FPS) -> dict[str, list[float]]:
    """Phoneme-level curves from (letter, start_s, end_s) timing of the TTS model."""
    n = max(1, int(np.ceil(len(data) / sr * fps)))
    target = np.zeros((n, 5), dtype=np.float32)
    for token, a, b in timing:
        ch = token.strip().lower()
        v = LETTER_VISEME.get(ch[:1], "X") if ch else "X"   # blanks, spaces, punctuation: rest
        f0, f1 = int(np.floor(max(0.0, a) * fps)), int(np.ceil(max(0.0, b) * fps))
        for f in range(f0, min(n, max(f1, f0 + 1))):
            if v != "X":
                target[f] = np.maximum(target[f], VISEMES[v])
    # coarticulation: blend neighbouring frames, then gate by loudness so pauses close the mouth
    kernel = np.array([0.25, 0.5, 0.25], dtype=np.float32)
    smooth = np.stack([np.convolve(target[:, k], kernel, mode="same") for k in range(5)], axis=1)
    env = _envelope01(data, sr, fps)
    env = np.pad(env, (0, max(0, n - len(env))))[:n]
    gate = np.clip(env * 1.6, 0.0, 1.0)[:, None]
    out = smooth * np.concatenate([gate[:, :1].repeat(3, axis=1), np.ones((n, 2), dtype=np.float32)], axis=1)
    out[:, 3] *= (gate[:, 0] > 0.05) | (smooth[:, 3] > 0.5)   # lips stay pressed for m/b/p even when quiet
    out[-1] = 0.0
    keys = ("open", "wide", "round", "mbp", "fv")
    return {k: [round(float(x), 3) for x in out[:, i] * (0.9 if k == "open" else 1.0)] for i, k in enumerate(keys)}


def lipsync_from_array(data: np.ndarray, sr: int, fps: int = FPS) -> dict[str, list[float]]:
    """Loudness-level curves (no letter timing available)."""
    env = frame_envelope(data, sr, fps)
    if len(env) == 0:
        return {"open": [], "wide": [], "round": [], "mbp": [], "fv": []}
    cen = frame_spectral_centroid(data, sr, fps)
    raw = _envelope01(data, sr, fps) ** 0.8
    smooth = np.zeros_like(raw)
    prev = 0.0
    for i, v in enumerate(raw):  # attack fast, release slower: mouths snap open and relax shut
        prev = prev + (v - prev) * (0.75 if v > prev else 0.45)
        smooth[i] = prev
    smooth[-1] = 0.0
    chatter = 1.0 - 0.18 * (np.arange(len(smooth)) % 3 == 2)  # long vowels do not freeze
    open_ = np.clip(smooth * chatter, 0, 1)
    wide = open_ * np.clip((cen - 1500.0) / 1800.0, 0, 1) * 0.8
    rnd = open_ * np.clip((1300.0 - cen) / 800.0, 0, 1) * 0.9
    zeros = [0.0] * len(open_)
    return {"open": [round(float(x), 3) for x in open_ * 0.9], "wide": [round(float(x), 3) for x in wide],
            "round": [round(float(x), 3) for x in rnd], "mbp": zeros, "fv": list(zeros)}
