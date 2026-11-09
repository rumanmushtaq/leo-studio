"""AI video mode against a mock ComfyUI server (no GPU needed)."""
import numpy as np
import pytest
from PIL import Image

from engines.ai_video import workflows
from engines.ai_video.comfy_client import ComfyClient, ComfyError
from engines.ai_video.renderer import AISettings, AIVideoRenderer
from engines.ai_video.shot_planner import plan_scene, segments
from tests.mock_comfy import ALL_NODES, MockComfy
from tests.test_motion_timeline import fake_audio
from utils.audio_utils import write_wav
from utils.config import AUDIO_SAMPLE_RATE, FPS
from utils.ffmpeg_utils import probe


@pytest.fixture
def mock(tmp_path):
    m = MockComfy(tmp_path / "comfy")
    yield m
    m.close()


def scene_with_audio(parsed_leo, registry, tmp_path, idx=1):
    from core.timeline_manager import TimelineManager

    audio = fake_audio(parsed_leo, 1.5)
    t = np.arange(int(1.5 * AUDIO_SAMPLE_RATE)) / AUDIO_SAMPLE_RATE
    for a in audio.values():
        a.path = str(tmp_path / f"{a.id}.wav")
        write_wav(a.path, (0.4 * np.sin(2 * np.pi * 180 * t)).astype(np.float32))
    tl = TimelineManager(registry).build(parsed_leo, audio)
    return tl["scenes"][idx]


def test_templates_fill_all_placeholders():
    wf = workflows.fill(workflows.load("i2v"), IMAGE="a.png", PROMPT="p", NEGATIVE="n", SEED=1, WIDTH=1280,
                        HEIGHT=704, FRAMES=121, FPS=24, STEPS=20)
    assert wf["8"]["inputs"]["length"] == 121 and wf["9"]["inputs"]["seed"] == 1
    with pytest.raises(KeyError):
        workflows.fill(workflows.load("restyle"), IMAGE="a.png")


def test_segments_cover_shot():
    assert segments(100) == [121]
    assert len(segments(300)) == 3          # 3 x 120 new frames >= 300


def test_client_roundtrip(mock, tmp_path):
    c = ComfyClient(mock.url)
    assert "Mock RTX 4090" in c.describe()
    img = tmp_path / "k.png"
    Image.new("RGB", (64, 64), "red").save(img)
    wf = workflows.fill(workflows.load("restyle"), IMAGE=c.upload(img), PROMPT="leo", SEED=3, WIDTH=320,
                        HEIGHT=176, DENOISE=0.5)
    out = c.run(wf, tmp_path / "dl", "styled")
    assert Image.open(out).size == (320, 176)


def test_missing_nodes_reported(tmp_path):
    m = MockComfy(tmp_path / "c2", nodes=[n for n in ALL_NODES if n != "Wan22ImageToVideoLatent"])
    try:
        wf = workflows.fill(workflows.load("i2v"), IMAGE="a.png", PROMPT="p", NEGATIVE="n", SEED=1, WIDTH=64,
                            HEIGHT=64, FRAMES=5, FPS=24, STEPS=1)
        with pytest.raises(ComfyError, match="Wan22ImageToVideoLatent"):
            ComfyClient(m.url).queue(wf)
    finally:
        m.close()


def test_unreachable_server_message():
    with pytest.raises(ComfyError, match="Cannot reach ComfyUI"):
        ComfyClient("http://127.0.0.1:9", timeout=2).describe()


def test_shot_prompts(parsed_leo, registry, tmp_path):
    sd = scene_with_audio(parsed_leo, registry, tmp_path, idx=1)   # Leo's entry
    specs = {cid: s.data for cid, s in registry.characters.items()}
    shots = plan_scene(sd, specs)
    assert len(shots) == len(sd["camera_shots"])
    assert all("Pixar" in s.image_prompt for s in shots)
    assert any("flying" in s.motion_prompt for s in shots)                 # fly-in tracking shot
    assert any(s.lipsync for s in shots)                                   # dialogue shots get lip-sync audio
    assert sum(s.frames for s in shots) == sd["frame_count"]


def test_render_scene_exact_length(mock, parsed_leo, registry, tmp_path):
    sd = scene_with_audio(parsed_leo, registry, tmp_path, idx=1)
    specs = {cid: s.data for cid, s in registry.characters.items()}
    shots = plan_scene(sd, specs)
    keys = {}
    for s in shots:
        keys[s.index] = tmp_path / f"key{s.index}.png"
        Image.new("RGB", (640, 360), (200, 150, 90)).save(keys[s.index])
    r = AIVideoRenderer(AISettings(server=mock.url, width=320, height=192, clip_frames=49, steps=1),
                        tmp_path / "work")
    out = r.render_scene(shots, keys, sd["frame_count"], tmp_path / "scene.mp4")
    v = probe(out, count_frames=True).video
    assert v.frames == sd["frame_count"] and (v.width, v.height) == (1280, 720) and abs(v.fps - FPS) < 0.01
    assert r.report["shots"] == len(shots) and r.report["lipsynced"] > 0
    jobs_before = len(mock.jobs)
    r2 = AIVideoRenderer(AISettings(server=mock.url, width=320, height=192, clip_frames=49, steps=1),
                         tmp_path / "work")
    r2.render_scene(shots, keys, sd["frame_count"], tmp_path / "scene2.mp4")
    assert len(mock.jobs) == jobs_before                                   # everything came from the cache


def test_lipsync_skipped_when_node_missing(parsed_leo, registry, tmp_path):
    m = MockComfy(tmp_path / "c3", nodes=[n for n in ALL_NODES if n != "LatentSyncNode"])
    try:
        sd = scene_with_audio(parsed_leo, registry, tmp_path, idx=1)
        shots = [s for s in plan_scene(sd, {cid: s.data for cid, s in registry.characters.items()}) if s.lipsync][:2]
        keys = {}
        for s in shots:
            keys[s.index] = tmp_path / f"k{s.index}.png"
            Image.new("RGB", (64, 64)).save(keys[s.index])
        r = AIVideoRenderer(AISettings(server=m.url, width=160, height=96, clip_frames=49, steps=1), tmp_path / "w")
        n = sum(s.frames for s in shots)
        r.render_scene(shots, keys, n, tmp_path / "x.mp4")
        assert r.report["lipsynced"] == 0 and "LatentSyncNode" in r.report["lipsync_skipped_reason"]
    finally:
        m.close()
