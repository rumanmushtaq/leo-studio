"""Audio helpers built on NumPy + soundfile (pydub used for format conversion)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from utils.config import AUDIO_SAMPLE_RATE, FPS


def read_audio(path: Path, sr: int = AUDIO_SAMPLE_RATE) -> np.ndarray:
    """Load any audio file as mono float32 at ``sr``.

    WAV/FLAC/OGG are read with soundfile; other formats (mp3, m4a) go through
    pydub, which shells out to FFmpeg.
    """
    path = Path(path)
    try:
        data, file_sr = sf.read(str(path), dtype="float32", always_2d=True)
        data = data.mean(axis=1)
    except RuntimeError:
        from pydub import AudioSegment

        seg = AudioSegment.from_file(str(path)).set_channels(1)
        file_sr = seg.frame_rate
        data = np.array(seg.get_array_of_samples(), dtype=np.float32) / float(1 << (8 * seg.sample_width - 1))
    if file_sr != sr:
        data = resample(data, file_sr, sr)
    return data.astype(np.float32)


def write_wav(path: Path, data: np.ndarray, sr: int = AUDIO_SAMPLE_RATE) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.clip(data, -1.0, 1.0), sr, subtype="PCM_16")


def resample(data: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    """Band-limited-enough linear resampling for speech/SFX."""
    if src_sr == dst_sr or len(data) == 0:
        return data
    n_out = int(round(len(data) * dst_sr / src_sr))
    x_old = np.linspace(0.0, 1.0, num=len(data), endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=n_out, endpoint=False)
    return np.interp(x_new, x_old, data).astype(np.float32)


def duration_seconds(data: np.ndarray, sr: int = AUDIO_SAMPLE_RATE) -> float:
    return len(data) / float(sr)


def normalize(data: np.ndarray, peak: float = 0.9) -> np.ndarray:
    m = float(np.max(np.abs(data))) if len(data) else 0.0
    return data if m < 1e-6 else (data * (peak / m)).astype(np.float32)


def trim_silence(data: np.ndarray, sr: int = AUDIO_SAMPLE_RATE, threshold: float = 0.01,
                 keep: float = 0.05) -> np.ndarray:
    """Trim leading/trailing silence, keeping ``keep`` seconds of padding."""
    idx = np.where(np.abs(data) > threshold)[0]
    if len(idx) == 0:
        return data
    pad = int(keep * sr)
    return data[max(0, idx[0] - pad): min(len(data), idx[-1] + pad)]


def trim_silence_offset(data: np.ndarray, sr: int = AUDIO_SAMPLE_RATE, threshold: float = 0.01,
                        keep: float = 0.05) -> tuple[np.ndarray, float]:
    """Like ``trim_silence`` but also returns how many seconds were cut from the start."""
    idx = np.where(np.abs(data) > threshold)[0]
    if len(idx) == 0:
        return data, 0.0
    pad = int(keep * sr)
    a = max(0, idx[0] - pad)
    return data[a: min(len(data), idx[-1] + pad)], a / sr


def fade(data: np.ndarray, sr: int, fade_in: float, fade_out: float) -> np.ndarray:
    out = data.copy()
    n_in, n_out = int(fade_in * sr), int(fade_out * sr)
    if n_in:
        out[:n_in] *= np.linspace(0, 1, min(n_in, len(out)))[: len(out[:n_in])]
    if n_out:
        out[-n_out:] *= np.linspace(1, 0, min(n_out, len(out)))[-len(out[-n_out:]):]
    return out


def frame_envelope(data: np.ndarray, sr: int = AUDIO_SAMPLE_RATE, fps: int = FPS) -> np.ndarray:
    """RMS loudness per video frame."""
    hop = sr / fps
    n = int(np.ceil(len(data) / hop))
    env = np.zeros(n, dtype=np.float32)
    for i in range(n):
        seg = data[int(i * hop): int((i + 1) * hop)]
        env[i] = float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0
    return env


def frame_spectral_centroid(data: np.ndarray, sr: int = AUDIO_SAMPLE_RATE, fps: int = FPS) -> np.ndarray:
    """Spectral centroid (Hz) per video frame; used as a crude vowel-brightness cue."""
    hop = sr / fps
    n = int(np.ceil(len(data) / hop))
    out = np.zeros(n, dtype=np.float32)
    for i in range(n):
        seg = data[int(i * hop): int((i + 1) * hop)]
        if len(seg) < 32:
            continue
        spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
        freqs = np.fft.rfftfreq(len(seg), 1.0 / sr)
        total = spec.sum()
        out[i] = float((spec * freqs).sum() / total) if total > 1e-9 else 0.0
    return out
