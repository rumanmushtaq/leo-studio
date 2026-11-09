"""Validation of parsed scripts and of the final rendered MP4."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from utils.config import FPS, MIN_VIDEO_SECONDS, OUTPUT_HEIGHT, OUTPUT_WIDTH
from utils.ffmpeg_utils import decode_errors, probe


@dataclass
class VideoCheck:
    ok: bool
    checks: dict[str, bool] = field(default_factory=dict)
    details: dict[str, object] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def verify_video(path: Path, expected_seconds: float | None = None,
                 expected_frames: int | None = None) -> VideoCheck:
    """Check stream layout, resolution, fps, duration, A/V sync and decodability."""
    info = probe(path, count_frames=True)
    v, a = info.video, info.audio
    res = VideoCheck(ok=True)
    res.details.update({
        "duration": round(info.duration, 3),
        "probe_tool": info.probe_tool,
        "video_codec": v.codec if v else None,
        "audio_codec": a.codec if a else None,
        "resolution": f"{v.width}x{v.height}" if v else None,
        "fps": round(v.fps, 3) if v else None,
        "frames": v.frames if v else None,
        "video_duration": round(v.duration, 3) if v else None,
        "audio_duration": round(a.duration, 3) if a else None,
    })
    res.checks["video_stream"] = v is not None
    res.checks["audio_stream"] = a is not None
    res.checks["h264"] = bool(v and v.codec == "h264")
    res.checks["aac"] = bool(a and a.codec == "aac")
    res.checks["resolution_1280x720"] = bool(v and (v.width, v.height) == (OUTPUT_WIDTH, OUTPUT_HEIGHT))
    res.checks["fps_24"] = bool(v and abs(v.fps - FPS) < 0.01)
    res.checks["duration_min_60s"] = info.duration >= MIN_VIDEO_SECONDS
    if v and a and v.duration and a.duration:
        res.checks["av_sync_within_100ms"] = abs(v.duration - a.duration) <= 0.1
    if expected_frames is not None and v:
        res.checks["frame_count"] = abs(v.frames - expected_frames) <= 1
    if expected_seconds is not None:
        res.checks["expected_duration"] = abs(info.duration - expected_seconds) <= 0.15
    errs = decode_errors(path)
    res.checks["decodes_cleanly"] = not errs
    res.errors += errs[:10]
    res.ok = all(res.checks.values())
    return res


def check_frames(frames_dir: Path, expected: int) -> dict:
    """OpenCV pass over rendered frames: missing, unreadable or blank (flat) images."""
    import cv2

    frames = sorted(Path(frames_dir).glob("frame_*.jpg"))
    unreadable, blank = [], []
    for f in frames:
        img = cv2.imread(str(f), cv2.IMREAD_GRAYSCALE)
        if img is None:
            unreadable.append(f.name)
        elif float(img.std()) < 4.0:
            blank.append(f.name)
    return {"expected": expected, "found": len(frames), "missing": max(0, expected - len(frames)),
            "unreadable": unreadable, "blank": blank,
            "ok": len(frames) >= expected and not unreadable and not blank}
