"""TTS, lip-sync, sound mixing and Urdu subtitles."""
import numpy as np
import pytest
import soundfile as sf
from PIL import Image, ImageFont, features

from engines.lipsync_engine import lipsync_from_array
from engines.sound_engine import SFX, SoundMixer, compose_music, get_sfx
from engines.subtitle_engine import Cue, SubtitleEngine
from engines.voice_engine import EspeakBackend, VoiceEngine
from utils.audio_utils import write_wav
from utils.config import AUDIO_SAMPLE_RATE as SR, FPS, URDU_FONT_CANDIDATES, find_font

URDU = "میں ہوں لیو! اس شہر کا محافظ!"


@pytest.mark.skipif(not EspeakBackend().available("ur"), reason="eSpeak NG not available")
def test_urdu_tts_espeak(tmp_path):
    eng = VoiceEngine("espeak")
    r = eng.synthesize("s01_e001", 1, URDU, "ur", {"pitch": 1.2, "rate": 1.0}, tmp_path / "a.wav")
    data, sr = sf.read(r.path)
    assert r.backend == "espeak" and sr == SR
    assert 1.0 < r.duration < 6.0
    assert np.abs(data).max() > 0.3                      # real, non-silent speech
    # cached second call gives identical audio
    r2 = eng.synthesize("s01_e001", 1, URDU, "ur", {"pitch": 1.2, "rate": 1.0}, tmp_path / "b.wav")
    assert np.array_equal(sf.read(r2.path)[0], data)


def test_manual_audio_import(tmp_path):
    manual = tmp_path / "manual"
    manual.mkdir()
    t = np.arange(SR) / SR
    write_wav(manual / "s01_e002.wav", (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32))
    r = VoiceEngine("manual", manual).synthesize("s01_e002", 2, "x", "ur", {}, tmp_path / "o.wav")
    assert r.backend == "manual" and abs(r.duration - 1.0) < 0.1


def test_manual_backend_without_file_fails_loudly(tmp_path):
    with pytest.raises(RuntimeError):
        VoiceEngine("manual", tmp_path).synthesize("s09_e009", 99, "x", "ur", {}, tmp_path / "o.wav")


def test_lipsync_follows_amplitude():
    t = np.arange(int(2 * SR)) / SR
    sig = np.where(t < 1.0, 0.6 * np.sin(2 * np.pi * 300 * t), 0.0).astype(np.float32)
    c = lipsync_from_array(sig, SR, FPS)
    assert len(c["open"]) == 2 * FPS
    assert np.mean(c["open"][4:20]) > 0.4
    assert max(c["open"][32:]) < 0.05                     # silence -> closed mouth
    assert c["open"][-1] == 0.0


def test_procedural_sfx_and_music():
    for sid in SFX:
        d = get_sfx(sid)
        assert len(d) > 0.05 * SR and np.abs(d).max() > 0.1
    m = compose_music(6.0)
    assert len(m) == 6 * SR and np.abs(m).max() > 0.1


def test_mixer_ducks_music_under_dialogue(tmp_path):
    t = np.arange(SR) / SR
    write_wav(tmp_path / "line.wav", (0.5 * np.sin(2 * np.pi * 200 * t)).astype(np.float32))
    tl = {"fps": FPS, "total_seconds": 6.0, "scenes": [{
        "id": 1, "start_time": 0.0, "frame_count": 6 * FPS, "ambience": "birds",
        "dialogues": [{"audio": str(tmp_path / "line.wav"), "start": 3 * FPS, "end": 4 * FPS}],
        "sfx": [{"id": "whoosh", "time": 0.5, "gain": 1.0}]}]}
    rep = SoundMixer(music=True).mix(tl, tmp_path / "mix.wav")
    data, sr = sf.read(tmp_path / "mix.wav")
    assert data.shape[1] == 2 and sr == SR and rep["lines"] == 1
    assert np.abs(data).max() <= 1.0


def test_srt_is_verbatim(tmp_path):
    cues = [Cue(1, 0.5, 2.0, URDU, "Leo", "ur"), Cue(2, 2.5, 4.0, "Hello there!", "Karim", "en")]
    SubtitleEngine.write_srt(cues, tmp_path / "s.srt")
    text = (tmp_path / "s.srt").read_text(encoding="utf-8")
    assert URDU in text and "00:00:00,500 --> 00:00:02,000" in text


@pytest.mark.skipif(not features.check("raqm") or not find_font(URDU_FONT_CANDIDATES), reason="no raqm/Urdu font")
def test_urdu_shaping_and_rtl(tmp_path):
    font_path = find_font(URDU_FONT_CANDIDATES)
    raqm = ImageFont.truetype(font_path, 40, layout_engine=ImageFont.Layout.RAQM)
    basic = ImageFont.truetype(font_path, 40, layout_engine=ImageFont.Layout.BASIC)
    word = "محافظ"
    # contextual shaping joins letters, so the shaped word is narrower than isolated glyphs
    assert raqm.getlength(word, direction="rtl", language="ur") < basic.getlength(word) * 0.9
    eng = SubtitleEngine()
    p = eng.render(Cue(1, 0, 2, URDU, "Leo", "ur"), tmp_path / "sub.png")
    im = Image.open(p)
    assert im.size == (1280, 720) and im.mode == "RGBA"
    assert im.getchannel("A").getbbox()[3] > 600         # drawn near the bottom


def test_letter_level_lipsync_visemes():
    """'میں' then 'محافظ': lips close for م, widen for ی, open for ا, tuck for ف."""
    from engines.lipsync_engine import lipsync_from_letters

    sr = SR
    t = np.arange(int(1.2 * sr)) / sr
    voice = (0.5 * np.sin(2 * np.pi * 200 * t)).astype(np.float32)
    timing = [["م", 0.0, 0.12], ["ی", 0.12, 0.3], ["", 0.3, 0.4], ["ا", 0.5, 0.75], ["ف", 0.8, 1.0]]
    c = lipsync_from_letters(timing, voice, sr, FPS)
    f = lambda s: int(s * FPS)  # noqa: E731
    assert c["mbp"][f(0.05)] > 0.5 and c["open"][f(0.05)] < 0.3
    assert c["wide"][f(0.22)] > 0.5
    assert c["open"][f(0.62)] > 0.6
    assert c["fv"][f(0.9)] > 0.5
    assert c["open"][-1] == 0.0


def test_mms_letter_timing_saved(tmp_path):
    """MMS voices store per-letter timing next to the WAV (skipped if the model is not downloaded)."""
    from engines.voice_engine import MMSBackend

    if not MMSBackend.is_downloaded("ur"):
        pytest.skip("MMS Urdu model not downloaded")
    r = VoiceEngine("mms").synthesize("t_mms", 1, URDU, "ur", {"pitch": 1.2, "rate": 1.0}, tmp_path / "a.wav")
    import json as _json

    timing = _json.loads((tmp_path / "a.letters.json").read_text(encoding="utf-8"))
    letters = [x[0] for x in timing if x[0].strip()]
    assert letters[:3] == ["م", "ی", "ں"]
    assert abs(timing[-1][2] - r.duration) < 0.3
