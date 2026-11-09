"""Local text-to-speech for Urdu and English dialogue.

Backends, in order of preference ("auto"):
  1. Meta MMS-TTS (VITS) via Hugging Face Transformers, run locally on CPU.
     Urdu: facebook/mms-tts-urd-script_arabic, English: facebook/mms-tts-eng.
     License: CC-BY-NC-4.0 (non-commercial use only). ~145 MB per language.
  2. eSpeak NG (bundled by the ``espeakng-loader`` wheel, GPL-3.0). Robotic but
     real, fully offline Urdu ("ur") and English voices.
  3. Manual import: user-supplied WAV/MP3 per line (always takes priority when
     a file for that line exists).
If no backend can voice a line, generation stops with an explanatory error;
speech is never faked.

MMS is a single-speaker model, so character voices are differentiated by a
controlled pitch shift (resampling) combined with the model's native
``speaking_rate``; the rate is pre-compensated so the final tempo matches the
character profile. This changes timbre and pitch, not the speaker identity.
"""
from __future__ import annotations

import ctypes
import gc
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from utils.audio_utils import normalize, read_audio, resample, trim_silence, trim_silence_offset, write_wav
from utils.config import AUDIO_SAMPLE_RATE, MODEL_CACHE
from utils.logger import get_logger

log = get_logger("voice")

MMS_MODELS = {"ur": "facebook/mms-tts-urd-script_arabic", "en": "facebook/mms-tts-eng"}
TTS_CACHE = MODEL_CACHE / "tts_cache"


class VoiceError(RuntimeError):
    pass


@dataclass
class VoiceResult:
    path: Path
    duration: float
    backend: str


def _clean_text(text: str) -> str:
    """Speakable text: same words, minus newlines and characters TTS cannot voice."""
    t = re.sub(r"\s+", " ", text).strip()
    return t


class MMSBackend:
    name = "mms"

    def __init__(self) -> None:
        self._models: dict[str, tuple] = {}
        self.last_timing: list[tuple[str, float, float]] = []  # (letter, start_s, end_s) of the last synth

    @staticmethod
    def is_downloaded(lang: str) -> bool:
        repo = MMS_MODELS[lang].replace("/", "--")
        return any((MODEL_CACHE / "hf").glob(f"models--{repo}/snapshots/*/config.json"))

    def available(self, lang: str, allow_download: bool) -> bool:
        if self.is_downloaded(lang):
            return True
        if not allow_download:
            return False
        try:
            self._load(lang)
            return True
        except Exception as exc:  # network / rate limit / missing torch
            log.warning("MMS-TTS model for '%s' unavailable: %s", lang, str(exc).splitlines()[0][:200])
            return False

    def _load(self, lang: str):
        if lang in self._models:
            return self._models[lang]
        import torch  # noqa: F401  (imported lazily: ~300 MB RAM)
        from transformers import AutoTokenizer, VitsModel

        repo = MMS_MODELS[lang]
        cache = str(MODEL_CACHE / "hf")
        offline = self.is_downloaded(lang)
        tok = AutoTokenizer.from_pretrained(repo, cache_dir=cache, local_files_only=offline)
        model = VitsModel.from_pretrained(repo, cache_dir=cache, local_files_only=offline)
        model.eval()
        self._models[lang] = (tok, model)
        return self._models[lang]

    def synth(self, text: str, lang: str, rate: float, seed: int) -> tuple[np.ndarray, int]:
        import torch

        tok, model = self._load(lang)
        inputs = tok(text, return_tensors="pt")
        if inputs["input_ids"].shape[-1] == 0:
            raise VoiceError(f"MMS tokenizer produced no tokens for: {text[:40]}")
        model.speaking_rate = float(rate)
        model.noise_scale = 0.6
        torch.manual_seed(seed)
        captured: dict = {}
        # The VITS duration predictor decides how long every input letter is spoken; capture it
        # so lip-sync can follow the actual letters (phoneme-level) instead of loudness only.
        hook = model.duration_predictor.register_forward_hook(lambda m, i, o: captured.__setitem__("log_dur", o))
        try:
            with torch.no_grad():
                wav = model(**inputs).waveform[0].cpu().numpy().astype(np.float32)
        finally:
            hook.remove()
        sr = int(model.config.sampling_rate)
        self.last_timing = []
        if "log_dur" in captured:
            hop = int(np.prod(model.config.upsample_rates))
            frames = torch.ceil(torch.exp(captured["log_dur"]) / float(rate))[0, 0].cpu().numpy()
            toks = tok.convert_ids_to_tokens(inputs["input_ids"][0].tolist())
            if getattr(tok, "add_blank", False):  # VITS intersperses a blank token before every letter
                toks = ["" if i % 2 == 0 else t_ for i, t_ in enumerate(toks)]
            t = 0.0
            for token, n in zip(toks, frames):
                dur = float(n) * hop / sr
                self.last_timing.append((token, t, t + dur))
                t += dur
        return wav, sr

    def unload(self) -> None:
        self._models.clear()
        gc.collect()


class EspeakBackend:
    name = "espeak"
    _lib = None
    _sr = 22050

    def available(self, lang: str, allow_download: bool = False) -> bool:
        try:
            self._init()
            return True
        except Exception as exc:
            log.warning("eSpeak NG unavailable: %s", exc)
            return False

    def _init(self) -> None:
        if EspeakBackend._lib is not None:
            return
        import espeakng_loader

        lib = ctypes.CDLL(espeakng_loader.get_library_path())
        data = espeakng_loader.get_data_path()
        lib.espeak_Initialize.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
        lib.espeak_Initialize.restype = ctypes.c_int
        sr = lib.espeak_Initialize(2, 0, os.path.dirname(data).encode(), 0)  # AUDIO_OUTPUT_SYNCHRONOUS
        if sr <= 0:
            sr = lib.espeak_Initialize(2, 0, data.encode(), 0)
        if sr <= 0:
            raise VoiceError("espeak_Initialize failed")
        EspeakBackend._lib = lib
        EspeakBackend._sr = sr

    def synth(self, text: str, lang: str, rate: float, seed: int) -> tuple[np.ndarray, int]:
        self._init()
        lib = EspeakBackend._lib
        chunks: list[np.ndarray] = []
        CB = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(ctypes.c_short), ctypes.c_int, ctypes.c_void_p)

        def _cb(wav, n, events):
            if n > 0:
                chunks.append(np.ctypeslib.as_array(wav, shape=(n,)).astype(np.float32) / 32768.0)
            return 0

        cb = CB(_cb)
        lib.espeak_SetSynthCallback(cb)
        if lib.espeak_SetVoiceByName(("ur" if lang == "ur" else "en").encode()) != 0:
            raise VoiceError(f"eSpeak voice for '{lang}' not found")
        lib.espeak_SetParameter(1, int(150 * rate), 0)  # espeakRATE (words per minute)
        data = text.encode("utf-8")
        lib.espeak_Synth.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_uint, ctypes.c_int, ctypes.c_uint,
                                     ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
        res = lib.espeak_Synth(data, len(data) + 1, 0, 1, 0, 1, None, None)  # POS_CHARACTER, espeakCHARS_UTF8
        lib.espeak_Synchronize()
        if res != 0 or not chunks:
            raise VoiceError(f"eSpeak synthesis failed (code {res})")
        return np.concatenate(chunks), EspeakBackend._sr


class VoiceEngine:
    """Generates one WAV per dialogue line with a per-character voice profile."""

    def __init__(self, backend: str = "auto", manual_dir: Path | None = None, allow_download: bool = True):
        self.backend_pref = backend
        self.manual_dir = Path(manual_dir) if manual_dir else None
        self.allow_download = allow_download
        self.mms = MMSBackend()
        self.espeak = EspeakBackend()
        self.used: dict[str, int] = {}
        self._avail: dict[tuple[str, str], bool] = {}
        TTS_CACHE.mkdir(parents=True, exist_ok=True)

    def _backend_for(self, lang: str):
        order = {"auto": ["mms", "espeak"], "mms": ["mms"], "espeak": ["espeak"], "manual": []}[self.backend_pref]
        for name in order:
            key = (name, lang)
            if key not in self._avail:
                b = self.mms if name == "mms" else self.espeak
                self._avail[key] = b.available(lang, self.allow_download)
            if self._avail[key]:
                return self.mms if name == "mms" else self.espeak
        return None

    def _manual_file(self, line_id: str, ordinal: int) -> Path | None:
        if not self.manual_dir or not self.manual_dir.is_dir():
            return None
        for stem in (line_id, f"{ordinal:03d}", str(ordinal)):
            for ext in (".wav", ".mp3", ".ogg", ".flac", ".m4a"):
                p = self.manual_dir / f"{stem}{ext}"
                if p.exists():
                    return p
        return None

    def synthesize(self, line_id: str, ordinal: int, text: str, lang: str, voice: dict, out_path: Path
                   ) -> VoiceResult:
        manual = self._manual_file(line_id, ordinal)
        if manual is not None:
            data = trim_silence(read_audio(manual))
            write_wav(out_path, data)
            self.used["manual"] = self.used.get("manual", 0) + 1
            return VoiceResult(out_path, len(data) / AUDIO_SAMPLE_RATE, "manual")
        backend = self._backend_for(lang)
        if backend is None:
            raise VoiceError(
                f"No TTS backend can voice line {line_id} ({lang}). Install the MMS model (needs internet once) "
                f"or eSpeak NG, or put a recording named {line_id}.wav in the manual audio folder.")
        text_c = _clean_text(text)
        pitch = float(voice.get("pitch", 1.0))
        rate = float(voice.get("rate", 1.0))
        seed = int(hashlib.md5(line_id.encode()).hexdigest()[:6], 16)
        key = hashlib.sha1(json.dumps(["v3", backend.name, lang, text_c, pitch, rate, seed]).encode()).hexdigest()
        cached = TTS_CACHE / f"{key}.wav"
        timing_file = cached.with_suffix(".letters.json")
        if cached.exists():
            data = read_audio(cached)
        else:
            # Pitch shift by resampling raises pitch AND tempo by `pitch`; ask the
            # model for rate/pitch so the final tempo equals the profile's rate.
            if backend.name == "espeak":
                self._espeak_pitch(pitch)
            wav, sr = backend.synth(text_c, lang, rate / pitch if backend.name == "mms" else rate, seed)
            data = resample(wav, int(round(sr * pitch)), AUDIO_SAMPLE_RATE) if backend.name == "mms" else \
                resample(wav, sr, AUDIO_SAMPLE_RATE)
            data, offset = trim_silence_offset(data)
            data = normalize(data, 0.89)
            write_wav(cached, data)
            if backend.name == "mms" and self.mms.last_timing:
                # resampling by `pitch` scales time by 1/pitch; trimming shifts it by the cut lead-in
                timing = [(c, round(a / pitch - offset, 4), round(b / pitch - offset, 4))
                          for c, a, b in self.mms.last_timing]
                timing_file.write_text(json.dumps(timing, ensure_ascii=False), encoding="utf-8")
        write_wav(out_path, data)
        letters_out = Path(out_path).with_suffix(".letters.json")
        if timing_file.exists():
            letters_out.write_text(timing_file.read_text(encoding="utf-8"), encoding="utf-8")
        elif letters_out.exists():
            letters_out.unlink()
        self.used[backend.name] = self.used.get(backend.name, 0) + 1
        return VoiceResult(out_path, len(data) / AUDIO_SAMPLE_RATE, backend.name)

    @staticmethod
    def _espeak_pitch(pitch: float) -> None:
        if EspeakBackend._lib is not None:
            EspeakBackend._lib.espeak_SetParameter(3, int(max(0, min(99, 50 * pitch))), 0)  # espeakPITCH

    def close(self) -> None:
        self.mms.unload()
