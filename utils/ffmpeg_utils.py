"""FFmpeg / FFprobe helpers: running commands and probing media files."""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from utils.config import PROC_KW, find_ffmpeg, find_ffprobe
from utils.logger import get_logger

log = get_logger("ffmpeg")


class FFmpegError(RuntimeError):
    pass


def run_ffmpeg(args: list[str], cancel_check=None, timeout: float | None = None) -> None:
    """Run ffmpeg with ``args``; raise FFmpegError with stderr tail on failure."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise FFmpegError("FFmpeg not found. Install it: sudo apt install ffmpeg")
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *args]
    log.debug("ffmpeg %s", " ".join(args))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **PROC_KW)
    try:
        while True:
            try:
                out, err = proc.communicate(timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                if cancel_check and cancel_check():
                    proc.kill()
                    proc.wait()
                    raise FFmpegError("cancelled")
    finally:
        if proc.poll() is None:
            proc.kill()
    if proc.returncode != 0:
        tail = "\n".join(err.strip().splitlines()[-12:])
        raise FFmpegError(f"ffmpeg failed ({proc.returncode}):\n{tail}")


@dataclass
class StreamInfo:
    kind: str
    codec: str
    width: int = 0
    height: int = 0
    fps: float = 0.0
    sample_rate: int = 0
    channels: int = 0
    duration: float = 0.0
    frames: int = 0


@dataclass
class MediaInfo:
    path: Path
    duration: float
    streams: list[StreamInfo] = field(default_factory=list)
    probe_tool: str = "ffprobe"

    @property
    def video(self) -> StreamInfo | None:
        return next((s for s in self.streams if s.kind == "video"), None)

    @property
    def audio(self) -> StreamInfo | None:
        return next((s for s in self.streams if s.kind == "audio"), None)


def _rate(text: str) -> float:
    if "/" in text:
        n, d = text.split("/")
        return float(n) / float(d) if float(d) else 0.0
    return float(text or 0)


def probe(path: Path, count_frames: bool = False) -> MediaInfo:
    """Probe a media file with ffprobe, or by parsing ``ffmpeg -i`` if absent."""
    path = Path(path)
    ffprobe = find_ffprobe()
    if ffprobe:
        cmd = [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams"]
        if count_frames:
            cmd.append("-count_frames")
        cmd.append(str(path))
        res = subprocess.run(cmd, capture_output=True, text=True, **PROC_KW)
        if res.returncode != 0:
            raise FFmpegError(res.stderr.strip())
        data = json.loads(res.stdout)
        streams = []
        for s in data.get("streams", []):
            kind = s.get("codec_type", "")
            streams.append(StreamInfo(
                kind=kind,
                codec=s.get("codec_name", ""),
                width=int(s.get("width", 0) or 0),
                height=int(s.get("height", 0) or 0),
                fps=_rate(s.get("avg_frame_rate", "0/1")) if kind == "video" else 0.0,
                sample_rate=int(s.get("sample_rate", 0) or 0),
                channels=int(s.get("channels", 0) or 0),
                duration=float(s.get("duration", 0) or 0),
                frames=int(s.get("nb_read_frames", s.get("nb_frames", 0)) or 0),
            ))
        return MediaInfo(path, float(data.get("format", {}).get("duration", 0) or 0), streams)
    return _probe_with_ffmpeg(path, count_frames)


def _probe_with_ffmpeg(path: Path, count_frames: bool) -> MediaInfo:
    """Fallback when ffprobe is missing: parse ffmpeg's stream summary."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise FFmpegError("Neither ffprobe nor ffmpeg is installed")
    res = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)], capture_output=True, text=True, **PROC_KW)
    text = res.stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", text)
    if not m:
        raise FFmpegError(f"Cannot read media file {path}: {text.strip()[-300:]}")
    duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    streams: list[StreamInfo] = []
    for line in text.splitlines():
        sm = re.search(r"Stream #\S+: (Video|Audio): (\w+)", line)
        if not sm:
            continue
        if sm.group(1) == "Video":
            wh = re.search(r", (\d{2,5})x(\d{2,5})", line)
            fps = re.search(r"([\d.]+) fps", line)
            streams.append(StreamInfo("video", sm.group(2),
                                      int(wh.group(1)) if wh else 0, int(wh.group(2)) if wh else 0,
                                      float(fps.group(1)) if fps else 0.0, duration=duration))
        else:
            sr = re.search(r"(\d+) Hz", line)
            ch = 2 if "stereo" in line else 1 if "mono" in line else 0
            streams.append(StreamInfo("audio", sm.group(2), sample_rate=int(sr.group(1)) if sr else 0,
                                      channels=ch, duration=duration))
    info = MediaInfo(path, duration, streams, probe_tool="ffmpeg")
    if count_frames and info.video:
        res = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path), "-map", "0:v:0", "-f", "null", "-"],
                             capture_output=True, text=True, **PROC_KW)
        frames = re.findall(r"frame=\s*(\d+)", res.stderr)
        if frames:
            info.video.frames = int(frames[-1])
    return info


def decode_errors(path: Path) -> list[str]:
    """Fully decode a file and return any decoder error lines (empty == clean)."""
    ffmpeg = find_ffmpeg()
    res = subprocess.run([ffmpeg, "-v", "error", "-i", str(path), "-f", "null", "-"],
                         capture_output=True, text=True, **PROC_KW)
    return [line for line in res.stderr.splitlines() if line.strip()]
