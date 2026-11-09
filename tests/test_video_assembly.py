"""FFmpeg assembly: scene clips + cross-fade + subtitles + audio -> verified MP4."""
import numpy as np
from PIL import Image, ImageDraw

from engines.subtitle_engine import Cue, SubtitleEngine
from engines.video_assembler import VideoAssembler
from utils.config import AUDIO_SAMPLE_RATE as SR, FPS, TRANSITION_SECONDS
from utils.ffmpeg_utils import probe
from utils.validators import verify_video


def make_frames(d, n, color):
    d.mkdir(parents=True)
    for i in range(n):
        im = Image.new("RGB", (640, 360), color)
        ImageDraw.Draw(im).ellipse((i * 4, 100, i * 4 + 80, 180), fill="white")
        im.save(d / f"frame_{i:04d}.jpg")


def test_assemble(tmp_path):
    asm = VideoAssembler(preset="ultrafast")
    clips = []
    for k, color in enumerate(("#335", "#533")):
        fd = tmp_path / f"s{k}"
        make_frames(fd, 2 * FPS, color)
        clips.append((asm.encode_scene(fd, 2 * FPS, tmp_path / f"c{k}.mp4"), 2.0, "dissolve"))
    total = 4.0 - TRANSITION_SECONDS
    t = np.arange(int(total * SR)) / SR
    stereo = np.stack([0.3 * np.sin(2 * np.pi * 220 * t)] * 2, axis=1).astype(np.float32)
    import soundfile as sf

    sf.write(tmp_path / "a.wav", stereo, SR)
    sub = SubtitleEngine()
    cue = Cue(1, 0.5, 2.0, "میں ہوں لیو!", "Leo", "ur")
    sub.render(cue, tmp_path / "sub.png")
    out = asm.assemble(clips, [cue], tmp_path / "a.wav", tmp_path / "final.mp4", total)
    check = verify_video(out, expected_seconds=total, expected_frames=round(total * FPS))
    assert check.checks["h264"] and check.checks["aac"]
    assert check.checks["resolution_1280x720"] and check.checks["fps_24"]
    assert check.checks["av_sync_within_100ms"] and check.checks["frame_count"]
    assert check.checks["decodes_cleanly"]
    assert not check.checks["duration_min_60s"]      # the validator really checks the 60 s rule
    info = probe(out)
    assert info.audio.channels == 2
