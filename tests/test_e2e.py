"""End-to-end: Leo Urdu superhero story -> verified 3D MP4 (>= 60 s).

Opt-in because it renders thousands of frames:
    LEO_E2E=1 LEO_E2E_QUALITY=preview LEO_E2E_OUT=/some/dir python -m pytest tests/test_e2e.py -s
"""
import json
import os
from pathlib import Path

import pytest

from core.generation_controller import GenerationController
from tests.conftest import LEO_SCRIPT, requires_blender
from utils.config import GenerationSettings

pytestmark = [pytest.mark.e2e, requires_blender,
              pytest.mark.skipif(os.environ.get("LEO_E2E") != "1", reason="set LEO_E2E=1 to run")]


def test_leo_episode(tmp_path):
    out = Path(os.environ.get("LEO_E2E_OUT", tmp_path))
    st = GenerationSettings(output_dir=out, quality=os.environ.get("LEO_E2E_QUALITY", "preview"),
                            episode_name=os.environ.get("LEO_E2E_NAME", "leo_e2e"),
                            voice_backend=os.environ.get("LEO_E2E_VOICE", "auto"), keep_temp=False)
    last = [-1.0]

    def progress(p):
        if p.percent - last[0] >= 2 or p.stage in ("verify",):
            last[0] = p.percent
            print(f"{p.percent:5.1f}% {p.label} {p.message}", flush=True)

    res = GenerationController(st, progress).run(LEO_SCRIPT)
    assert res.ok, res.error
    rep = json.loads((res.episode_dir / "project.json").read_text())
    c = rep["checks"]
    assert c["duration_min_60s"] and c["video_stream"] and c["audio_stream"]
    assert c["resolution_1280x720"] and c["fps_24"] and c["h264"] and c["aac"]
    assert c["all_scenes_rendered"] and c["all_dialogue_accounted"] and c["decodes_cleanly"]
    assert c["av_sync_within_100ms"] and c["frame_count"]
    assert len(rep["scenes"]) == 6 and rep["dialogue_lines"] == 19
    shots = {s for sc in rep["scenes"] for s in sc["shots"]}
    assert {"establishing", "medium", "tracking", "low_angle"} <= shots
    srt = (res.episode_dir / "subtitles.srt").read_text(encoding="utf-8")
    assert "میں ہوں لیو! اس شہر کا محافظ!" in srt
    for f in ("leo.blend", "karim.blend", "bilal.blend", "ustad_akram.blend", "boss.blend"):
        assert (res.episode_dir / "characters" / f).exists()
    assert len(list((res.episode_dir / "scenes").glob("scene_*.blend"))) == 6
