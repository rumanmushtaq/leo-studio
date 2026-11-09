"""Windows/Linux portability: fallbacks used when platform features are missing."""
import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

import utils.config as cfg
from engines.subtitle_engine import Cue, SubtitleEngine
from utils import text_shaping as ts

URDU = "میں ہوں لیو! اس شہر کا محافظ!"


def test_fonts_are_bundled():
    for f in ("NotoNastaliqUrdu-Regular.ttf", "NotoNaskhArabic-Regular.ttf", "NotoSans-Bold.ttf"):
        assert (cfg.FONT_DIR / f).exists()
    assert cfg.find_font(cfg.URDU_FONT_CANDIDATES).startswith(str(cfg.FONT_DIR))


def test_urdu_without_raqm(tmp_path, monkeypatch):
    """Windows Pillow wheels usually lack FriBiDi -> raqm off -> reshaper + bidi fallback."""
    monkeypatch.setattr(ts, "raqm_available", lambda: False)
    ts.font.cache_clear()
    try:
        shown, kw = ts.prepare(URDU, "ur")
        assert kw == {} and shown != URDU                       # reordered + contextual forms
        assert any(0xFE70 <= ord(c) <= 0xFEFF for c in shown)   # Arabic presentation forms (joined letters)
        p = SubtitleEngine().render(Cue(1, 0, 2, URDU, "Leo", "ur"), tmp_path / "s.png")
        alpha = np.array(Image.open(p).getchannel("A"))
        assert alpha[560:, :].max() == 255 and alpha[:400, :].max() == 0
    finally:
        ts.font.cache_clear()


def test_srt_text_identical_with_either_backend(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "raqm_available", lambda: False)
    SubtitleEngine.write_srt([Cue(1, 0, 1, URDU, "Leo", "ur")], tmp_path / "a.srt")
    assert URDU in (tmp_path / "a.srt").read_text(encoding="utf-8")


def test_ffmpeg_from_pip_when_not_installed(tmp_path, monkeypatch):
    monkeypatch.delenv("LEO_FFMPEG", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    exe = cfg.find_ffmpeg()
    assert exe and "imageio_ffmpeg" in exe
    out = tmp_path / "t.mp4"
    res = subprocess.run([exe, "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=24", "-t", "1",
                          "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)], capture_output=True, **cfg.PROC_KW)
    assert res.returncode == 0 and out.stat().st_size > 1000


def test_child_process_output_is_utf8():
    assert cfg.PROC_KW["encoding"] == "utf-8" and cfg.PROC_KW["errors"] == "replace"


def test_windows_gpu_detection_uses_powershell(monkeypatch):
    from models import hardware_detector as hd

    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="Intel(R) UHD Graphics 620\nNVIDIA GeForce RTX 3060\n")

    monkeypatch.setattr(hd.platform, "system", lambda: "Windows")
    monkeypatch.setattr(hd.shutil, "which", lambda n: None)
    monkeypatch.setattr(hd.subprocess, "run", fake_run)
    gpus = hd._gpus()
    assert calls and calls[0][0] == "powershell" and "wmic" not in calls[0]
    assert "NVIDIA GeForce RTX 3060" in gpus


def test_windows_blender_search_paths(monkeypatch, tmp_path):
    exe = tmp_path / "Blender Foundation" / "Blender 4.5" / "blender.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    exe.chmod(0o755)
    monkeypatch.delenv("LEO_BLENDER", raising=False)
    monkeypatch.setattr(cfg.platform, "system", lambda: "Windows")
    monkeypatch.setattr(cfg.shutil, "which", lambda n: None)
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.setattr(cfg.Path, "home", lambda: Path("/nonexistent"))
    assert cfg.find_blender() == str(exe)
