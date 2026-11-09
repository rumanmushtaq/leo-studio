"""Procedural sound effects, original background music and the final mix.

Every sound here is synthesised from NumPy oscillators and noise, so all audio
is original to this project (no third-party samples, no copyright issues).
User-supplied, properly licensed WAV files in ``assets/sounds/<id>.wav`` or
``assets/music/*.wav`` override the generated ones.

Mixing: dialogue at full level; ambience and effects underneath; music is
ducked whenever anyone speaks (attack 0.15 s, release 0.5 s); scenes fade at
their boundaries; a soft limiter prevents clipping. Output: 44.1 kHz stereo.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from utils.audio_utils import read_audio, write_wav
from utils.config import AUDIO_SAMPLE_RATE, ASSETS_DIR, SOUND_LIBRARY
from utils.logger import get_logger

log = get_logger("sound")
SR = AUDIO_SAMPLE_RATE
GENERATED = SOUND_LIBRARY / "generated"


def _t(seconds: float) -> np.ndarray:
    return np.arange(int(seconds * SR)) / SR


def _noise(n: int, rng: np.random.Generator) -> np.ndarray:
    return rng.uniform(-1, 1, n).astype(np.float32)


def _lowpass(x: np.ndarray, cutoff: float | np.ndarray) -> np.ndarray:
    """One-pole low-pass; ``cutoff`` may vary per sample."""
    c = np.broadcast_to(np.asarray(cutoff, dtype=np.float64), x.shape)
    a = 1.0 - np.exp(-2 * np.pi * c / SR)
    y = np.empty_like(x, dtype=np.float64)
    acc = 0.0
    for i in range(len(x)):
        acc += a[i] * (x[i] - acc)
        y[i] = acc
    return y.astype(np.float32)


def _lp_fast(x: np.ndarray, cutoff: float) -> np.ndarray:
    """FFT brick-wall low-pass for long buffers (fixed cutoff)."""
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(len(x), 1 / SR)
    spec[freqs > cutoff] *= 0.0
    return np.fft.irfft(spec, n=len(x)).astype(np.float32)


def _bandpass(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(len(x), 1 / SR)
    spec[(freqs < lo) | (freqs > hi)] = 0
    return np.fft.irfft(spec, n=len(x)).astype(np.float32)


def _env(n: int, attack: float, release: float) -> np.ndarray:
    e = np.ones(n, dtype=np.float32)
    a, r = int(attack * SR), int(release * SR)
    if a:
        e[:a] = np.linspace(0, 1, a)
    if r:
        e[-r:] *= np.linspace(1, 0, r)
    return e


def _decay(n: int, tau: float) -> np.ndarray:
    return np.exp(-np.arange(n) / (tau * SR)).astype(np.float32)


def _norm(x: np.ndarray, peak: float = 0.9) -> np.ndarray:
    m = float(np.max(np.abs(x))) or 1.0
    return (x / m * peak).astype(np.float32)


def _place(dst: np.ndarray, src: np.ndarray, at: int, gain: float = 1.0) -> None:
    if at >= len(dst) or len(src) == 0:
        return
    if at < 0:
        src = src[-at:]
        at = 0
    n = min(len(src), len(dst) - at)
    dst[at:at + n] += src[:n] * gain


# ---------------------------------------------------------------- generators

def sfx_footsteps(rng) -> np.ndarray:
    n = int(0.12 * SR)
    thump = _lowpass(_noise(n, rng), 500) * _decay(n, 0.025) * 3
    thump += np.sin(2 * np.pi * 90 * _t(0.12)) * _decay(n, 0.02) * 0.6
    return _norm(thump, 0.8)


def sfx_flying(rng) -> np.ndarray:
    t = _t(2.2)
    cutoff = 300 + 2500 * np.sin(np.pi * t / 2.2) ** 2
    x = _lowpass(_noise(len(t), rng), cutoff) * np.sin(np.pi * t / 2.2) ** 1.5
    x += 0.15 * np.sin(2 * np.pi * (300 + 200 * t) * t) * np.sin(np.pi * t / 2.2)
    return _norm(x)


def sfx_whoosh(rng) -> np.ndarray:
    t = _t(0.7)
    x = _lowpass(_noise(len(t), rng), 400 + 3000 * np.sin(np.pi * t / 0.7)) * np.sin(np.pi * t / 0.7) ** 2
    return _norm(x, 0.7)


def sfx_landing(rng) -> np.ndarray:
    t = _t(0.9)
    boom = np.sin(2 * np.pi * (70 - 30 * t) * t) * _decay(len(t), 0.18)
    dust = _lowpass(_noise(len(t), rng), 900) * _decay(len(t), 0.3) * 0.6
    return _norm(boom + dust)


def _brass(freq: float, dur: float) -> np.ndarray:
    t = _t(dur)
    x = sum(np.sin(2 * np.pi * freq * k * t + 0.3 * k) / k ** 1.1 for k in range(1, 9))
    x *= 1 + 0.03 * np.sin(2 * np.pi * 5.5 * t)
    return (x * _env(len(t), 0.04, min(0.4, dur * 0.4))).astype(np.float32)


def sfx_hero_entrance(rng) -> np.ndarray:
    out = np.zeros(int(2.0 * SR), dtype=np.float32)
    for i, (f, d) in enumerate(((261.6, 0.25), (329.6, 0.25), (392.0, 0.25))):
        _place(out, _brass(f, d), int(i * 0.16 * SR), 0.6)
    chord = sum(_brass(f, 1.3) for f in (261.6, 329.6, 392.0, 523.3))
    _place(out, chord, int(0.5 * SR), 0.45)
    return _norm(out)


def sfx_magic(rng) -> np.ndarray:
    out = np.zeros(int(2.0 * SR), dtype=np.float32)
    notes = [523.3, 659.3, 784.0, 1046.5, 1318.5, 1568.0, 2093.0]
    for i, f in enumerate(notes):
        n = int(0.9 * SR)
        bell = (np.sin(2 * np.pi * f * _t(0.9)) + 0.4 * np.sin(2 * np.pi * f * 2.76 * _t(0.9))) * _decay(n, 0.25)
        _place(out, bell.astype(np.float32), int(i * 0.11 * SR), 0.5)
    out += _bandpass(_noise(len(out), rng), 4000, 9000) * 0.08 * _env(len(out), 0.1, 1.0)
    return _norm(out)


def sfx_shield(rng) -> np.ndarray:
    t = _t(2.4)
    hum = (np.sin(2 * np.pi * 110 * t) + 0.6 * np.sin(2 * np.pi * 220.5 * t) + 0.3 * np.sin(2 * np.pi * 331 * t))
    hum *= 0.6 + 0.4 * np.sin(2 * np.pi * 7 * t)
    sweep = np.sin(2 * np.pi * (200 + 600 * t / 2.4) * t) * 0.3
    return _norm((hum + sweep) * _env(len(t), 0.15, 0.8))


def sfx_motorcycle(rng) -> np.ndarray:
    t = _t(4.5)
    f0 = 38 + 30 * np.clip(t / 1.2, 0, 1) - 12 * np.clip((t - 3.0) / 1.5, 0, 1)
    phase = 2 * np.pi * np.cumsum(f0) / SR
    saw = 2 * ((phase / (2 * np.pi)) % 1.0) - 1
    x = _lowpass(saw.astype(np.float32), 900) + 0.3 * _lowpass(_noise(len(t), rng), 600)
    x *= 1 + 0.3 * np.sin(phase * 0.5)
    return _norm(x * _env(len(t), 0.2, 0.8), 0.8)


def sfx_car(rng) -> np.ndarray:
    t = _t(3.0)
    f0 = 28 + 6 * np.sin(2 * np.pi * 0.4 * t)
    phase = 2 * np.pi * np.cumsum(f0) / SR
    x = _lowpass(np.sign(np.sin(phase)).astype(np.float32), 400) * 0.5 + _lowpass(_noise(len(t), rng), 300) * 0.4
    beep = np.zeros_like(x)
    _place(beep, (np.sign(np.sin(2 * np.pi * 420 * _t(0.35))) * 0.25).astype(np.float32), int(1.8 * SR))
    return _norm((x + _lowpass(beep, 2500)) * _env(len(t), 0.3, 0.6), 0.7)


def sfx_police_siren(rng) -> np.ndarray:
    t = _t(3.6)
    f = 750 + 250 * np.sin(2 * np.pi * t / 1.2)
    x = np.sin(2 * np.pi * np.cumsum(f) / SR)
    return _norm(_lowpass(x.astype(np.float32), 3000) * _env(len(t), 0.2, 0.6), 0.6)


def sfx_crowd(rng) -> np.ndarray:
    t = _t(3.0)
    x = np.zeros(len(t), dtype=np.float32)
    for _ in range(14):
        f = rng.uniform(300, 900)
        voice = _bandpass(_noise(len(t), rng), f * 0.8, f * 1.6)
        voice *= (0.5 + 0.5 * np.sin(2 * np.pi * rng.uniform(2, 5) * t + rng.uniform(0, 6))).astype(np.float32)
        x += voice
    for _ in range(6):  # "yay" shouts
        at = rng.uniform(0.2, 2.2)
        f = rng.uniform(380, 650)
        shout = np.sin(2 * np.pi * f * _t(0.4) * (1 + 0.2 * _t(0.4))) * np.sin(np.pi * _t(0.4) / 0.4)
        _place(x, shout.astype(np.float32) * 0.6, int(at * SR))
    return _norm(x * _env(len(t), 0.3, 1.0), 0.7)


def sfx_transition(rng) -> np.ndarray:
    return sfx_whoosh(rng) * 0.6


def _clank(rng, f: float) -> np.ndarray:
    n = int(0.5 * SR)
    t = _t(0.5)
    x = sum(np.sin(2 * np.pi * f * r * t) * _decay(n, 0.08 / r ** 0.5) for r in (1, 2.4, 3.9, 5.3))
    return (x * 0.4 + _lowpass(_noise(n, rng), 3000) * _decay(n, 0.01)).astype(np.float32)


def amb_construction(rng, seconds: float) -> np.ndarray:
    out = _lp_fast(_noise(int(seconds * SR), rng), 250) * 0.25
    t = rng.uniform(0.2, 0.8)
    while t < seconds:
        _place(out, _clank(rng, rng.uniform(700, 1400)), int(t * SR), rng.uniform(0.3, 0.6))
        t += rng.uniform(0.55, 1.4)
    return out


def amb_workshop(rng, seconds: float) -> np.ndarray:
    out = _lp_fast(_noise(int(seconds * SR), rng), 180) * 0.25
    t = 0.5
    while t < seconds:
        if rng.random() < 0.5:
            for k in range(6):  # ratchet
                click = _bandpass(_noise(int(0.02 * SR), rng), 2000, 6000) * _decay(int(0.02 * SR), 0.004)
                _place(out, click, int((t + k * 0.07) * SR), 0.5)
        else:
            _place(out, _clank(rng, rng.uniform(900, 1800)), int(t * SR), 0.35)
        t += rng.uniform(1.0, 2.2)
    return out


def amb_traffic(rng, seconds: float) -> np.ndarray:
    n = int(seconds * SR)
    out = _lp_fast(_noise(n, rng), 200) * 0.35
    t = rng.uniform(0, 2)
    while t < seconds:
        d = rng.uniform(2.0, 3.5)
        swell = _lp_fast(_noise(int(d * SR), rng), 500) * np.sin(np.pi * _t(d) / d) ** 2
        _place(out, swell.astype(np.float32), int(t * SR), 0.5)
        t += rng.uniform(2.5, 5)
    return out


def amb_birds(rng, seconds: float) -> np.ndarray:
    n = int(seconds * SR)
    out = _lp_fast(_noise(n, rng), 300) * 0.12
    t = rng.uniform(0, 1)
    while t < seconds:
        f = rng.uniform(2500, 4200)
        for k in range(rng.integers(2, 5)):
            d = 0.08
            tt = _t(d)
            chirp = np.sin(2 * np.pi * (f + 1800 * tt / d) * tt) * np.sin(np.pi * tt / d)
            _place(out, chirp.astype(np.float32), int((t + k * 0.12) * SR), 0.25)
        t += rng.uniform(0.8, 2.5)
    return out


def amb_hideout_hum(rng, seconds: float) -> np.ndarray:
    t = _t(seconds)
    hum = 0.3 * np.sin(2 * np.pi * 55 * t) + 0.15 * np.sin(2 * np.pi * 110.3 * t)
    return (hum * (0.8 + 0.2 * np.sin(2 * np.pi * 0.2 * t)) + _lp_fast(_noise(len(t), rng), 150) * 0.2
            ).astype(np.float32)


def amb_crowd(rng, seconds: float) -> np.ndarray:
    base = sfx_crowd(rng)
    reps = int(math.ceil(seconds * SR / len(base)))
    return np.tile(base, reps)[: int(seconds * SR)] * 0.6


SFX = {"footsteps": sfx_footsteps, "flying": sfx_flying, "whoosh": sfx_whoosh, "landing": sfx_landing,
       "hero_entrance": sfx_hero_entrance, "magic": sfx_magic, "shield": sfx_shield, "motorcycle": sfx_motorcycle,
       "car": sfx_car, "police_siren": sfx_police_siren, "crowd": sfx_crowd, "transition": sfx_transition,
       "construction": lambda r: amb_construction(r, 2.5), "workshop": lambda r: amb_workshop(r, 3.0)}
AMBIENCE = {"construction": amb_construction, "workshop": amb_workshop, "traffic": amb_traffic,
            "birds": amb_birds, "hideout_hum": amb_hideout_hum, "crowd": amb_crowd}


def get_sfx(sid: str) -> np.ndarray:
    """Licensed user file if present, else cached procedural sound."""
    user = SOUND_LIBRARY / f"{sid}.wav"
    if user.exists():
        return read_audio(user)
    GENERATED.mkdir(parents=True, exist_ok=True)
    cached = GENERATED / f"{sid}.wav"
    if cached.exists():
        return read_audio(cached)
    gen = SFX.get(sid, sfx_whoosh)
    data = gen(np.random.default_rng(sum(map(ord, sid))))
    write_wav(cached, data)
    return data


# ------------------------------------------------------------------- music

NOTE = {n: 440.0 * 2 ** ((i - 9) / 12) for i, n in enumerate(["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A",
                                                             "A#", "B"])}
PROGRESSION = [("C", [0, 4, 7]), ("G", [7, 11, 14]), ("A", [9, 12, 16]), ("F", [5, 9, 12])]


def compose_music(seconds: float, seed: int = 7, bpm: float = 108.0) -> np.ndarray:
    """Original upbeat cartoon loop: bass, plucked chords, pentatonic melody, light drums."""
    rng = np.random.default_rng(seed)
    beat = 60.0 / bpm
    n = int(seconds * SR)
    out = np.zeros(n, dtype=np.float32)
    c4 = NOTE["C"]
    scale = [0, 2, 4, 7, 9, 12, 14, 16]
    motif = [int(rng.integers(0, len(scale))) for _ in range(8)]
    bar = 0
    t0 = 0.0
    while t0 < seconds:
        root_name, chord = PROGRESSION[bar % 4]
        for b in range(4):
            at = int((t0 + b * beat) * SR)
            # bass
            f = c4 / 2 * 2 ** (chord[0] / 12)
            tt = _t(beat * 0.9)
            bass = (np.sin(2 * np.pi * f * tt) + 0.3 * np.sign(np.sin(2 * np.pi * f * tt))) * _decay(len(tt), 0.25)
            _place(out, bass.astype(np.float32), at, 0.22)
            # plucked chord on beats 2 and 4
            if b % 2 == 1:
                tt = _t(beat * 0.8)
                pl = sum(np.sin(2 * np.pi * c4 * 2 ** (iv / 12) * tt) for iv in chord) * _decay(len(tt), 0.18)
                _place(out, pl.astype(np.float32), at, 0.08)
            # drums
            k = _t(0.25)
            kick = np.sin(2 * np.pi * (110 * np.exp(-k * 18) + 45) * k) * _decay(len(k), 0.08)
            if b % 2 == 0:
                _place(out, kick.astype(np.float32), at, 0.35)
            else:
                sn = _bandpass(_noise(int(0.18 * SR), rng), 1200, 7000) * _decay(int(0.18 * SR), 0.05)
                _place(out, sn, at, 0.12)
            hat = _bandpass(_noise(int(0.05 * SR), rng), 7000, 14000) * _decay(int(0.05 * SR), 0.012)
            _place(out, hat, at + int(beat / 2 * SR), 0.06)
        # melody: motif varied per bar
        for i in range(8):
            if rng.random() < 0.3:
                continue
            deg = scale[(motif[i] + bar) % len(scale)]
            f = c4 * 2 * 2 ** ((deg + (chord[0] % 12 if i % 4 == 0 else 0) * 0) / 12)
            tt = _t(beat * 0.45)
            note = (np.sin(2 * np.pi * f * tt) + 0.25 * np.sin(4 * np.pi * f * tt)) * _decay(len(tt), 0.15)
            _place(out, note.astype(np.float32), int((t0 + i * beat / 2) * SR), 0.07)
        t0 += 4 * beat
        bar += 1
    return _norm(out * _env(n, 1.5, 2.5), 0.8)


def get_music(seconds: float) -> np.ndarray:
    user = sorted((ASSETS_DIR / "music").glob("*.wav"))
    if user:
        data = read_audio(user[0])
        reps = int(math.ceil(seconds * SR / max(1, len(data))))
        return np.tile(data, reps)[: int(seconds * SR)] * _env(int(seconds * SR), 1.0, 2.5)
    return compose_music(seconds)


# -------------------------------------------------------------------- mixing

class SoundMixer:
    """Builds the episode master track from the timeline."""

    def __init__(self, music: bool = True):
        self.music = music
        self.report: dict[str, int] = {}

    def mix(self, timeline: dict, out_path: Path, sfx_dir: Path | None = None) -> dict:
        total = timeline["total_seconds"]
        n = int(math.ceil(total * SR)) + 1
        dialogue = np.zeros(n, dtype=np.float32)
        fx = np.zeros(n, dtype=np.float32)
        amb = np.zeros(n, dtype=np.float32)
        speech_mask = np.zeros(n, dtype=np.float32)
        fps = timeline["fps"]
        placed_lines = 0
        for sd in timeline["scenes"]:
            off = sd["start_time"]
            dur = sd["frame_count"] / fps
            for d in sd["dialogues"]:
                data = read_audio(Path(d["audio"]))
                at = int((off + d["start"] / fps) * SR)
                _place(dialogue, data, at, 1.0)
                speech_mask[at:at + len(data)] = 1.0
                placed_lines += 1
            for cue in sd["sfx"]:
                if cue["id"] == "music_cue" or cue.get("gain", 1) <= 0:
                    continue
                data = get_sfx(cue["id"])
                if cue.get("duration"):
                    data = data[: int(cue["duration"] * SR)]
                _place(fx, data, int((off + cue["time"]) * SR), 0.55 * cue.get("gain", 1.0))
                self.report[cue["id"]] = self.report.get(cue["id"], 0) + 1
                if sfx_dir is not None:
                    sfx_dir.mkdir(parents=True, exist_ok=True)
                    dst = sfx_dir / f"{cue['id']}.wav"
                    if not dst.exists():
                        write_wav(dst, data)
            gen = AMBIENCE.get(sd["ambience"])
            if gen is not None:
                bed = gen(np.random.default_rng(sd["id"]), dur) * _env(int(dur * SR), 0.6, 0.6)
                _place(amb, _norm(bed, 0.5), int(off * SR), 0.22)
                self.report["ambience:" + sd["ambience"]] = 1
        # ducking envelope: 0.15 s attack, 0.5 s release
        duck = np.zeros(n, dtype=np.float32)
        a, r = 1 - math.exp(-1 / (0.15 * SR / 64)), 1 - math.exp(-1 / (0.5 * SR / 64))
        acc = 0.0
        for i in range(0, n, 64):
            target = speech_mask[i:i + 64].max()
            acc += (target - acc) * (a if target > acc else r)
            duck[i:i + 64] = acc
        music = np.zeros(n, dtype=np.float32)
        if self.music:
            m = get_music(total)
            _place(music, m, 0, 1.0)
        music_gain = 0.32 - 0.22 * duck
        amb_gain = 1.0 - 0.45 * duck
        fx_gain = 1.0 - 0.3 * duck
        mono_bed = amb * amb_gain + fx * fx_gain
        left = dialogue + mono_bed + music * music_gain
        delay = int(0.012 * SR)  # small Haas delay widens the music
        music_r = np.concatenate([np.zeros(delay, np.float32), music[:-delay]])
        right = dialogue + mono_bed + music_r * music_gain
        stereo = np.stack([left, right], axis=1)
        stereo = np.tanh(stereo * 1.1) / np.tanh(1.1)  # soft limiter
        out_path.parent.mkdir(parents=True, exist_ok=True)
        import soundfile as sf

        sf.write(str(out_path), stereo.astype(np.float32), SR, subtype="PCM_16")
        log.info("Mixed %d dialogue lines, %d effect cues -> %s", placed_lines, sum(self.report.values()), out_path)
        return {"lines": placed_lines, "cues": dict(self.report), "seconds": n / SR}
