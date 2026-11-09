"""Final composition with FFmpeg.

1. Encode each scene's rendered JPEG frames into an intermediate clip
   (scaled to 1280x720 when rendered at preview resolution).
2. Join scenes with cross-dissolve or fade-through-black (``xfade``).
3. Overlay the pre-rendered subtitle PNGs at their cue times.
4. Mux the mixed stereo master track as AAC; H.264 yuv420p, 24 fps, faststart.
"""
from __future__ import annotations

from pathlib import Path

from engines.subtitle_engine import Cue
from utils.config import FPS, OUTPUT_HEIGHT, OUTPUT_WIDTH, TRANSITION_SECONDS
from utils.ffmpeg_utils import run_ffmpeg
from utils.logger import get_logger

log = get_logger("assembler")


class VideoAssembler:
    def __init__(self, cancel_check=None, crf: int = 20, preset: str = "medium"):
        self.cancel_check = cancel_check
        self.crf = crf
        self.preset = preset

    def encode_scene(self, frames_dir: Path, n_frames: int, out: Path) -> Path:
        frames = sorted(frames_dir.glob("frame_*.jpg"))
        if len(frames) < n_frames:
            raise RuntimeError(f"{frames_dir.name}: expected {n_frames} frames, found {len(frames)}")
        first = int(frames[0].stem.split("_")[1])
        run_ffmpeg(["-framerate", str(FPS), "-start_number", str(first), "-i", str(frames_dir / "frame_%04d.jpg"),
                    "-frames:v", str(n_frames),
                    "-vf", f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:flags=lanczos,format=yuv420p",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-r", str(FPS), str(out)],
                   self.cancel_check)
        return out

    def assemble(self, scene_clips: list[tuple[Path, float, str]], cues: list[Cue], audio: Path, out: Path,
                 total_seconds: float) -> Path:
        """``scene_clips``: (clip, duration_s, transition_into_next)."""
        args: list[str] = []
        for clip, _, _ in scene_clips:
            args += ["-i", str(clip)]
        n = len(scene_clips)
        sub_inputs = [c for c in cues if c.image]
        for c in sub_inputs:
            args += ["-loop", "1", "-framerate", str(FPS), "-t", f"{c.end - c.start:.3f}", "-i", str(c.image)]
        args += ["-i", str(audio)]
        audio_idx = n + len(sub_inputs)
        filters = []
        cur = "[0:v]"
        offset = 0.0
        for i in range(1, n):
            offset += scene_clips[i - 1][1] - TRANSITION_SECONDS
            trans = "fadeblack" if scene_clips[i][2] == "fadeblack" else "fade"
            label = f"[x{i}]"
            filters.append(f"{cur}[{i}:v]xfade=transition={trans}:duration={TRANSITION_SECONDS}:"
                           f"offset={offset:.4f}{label}")
            cur = label
        filters.append(f"{cur}fade=t=in:st=0:d=0.4,fade=t=out:st={max(0.0, total_seconds - 0.6):.3f}:d=0.6[base]")
        cur = "[base]"
        for k, c in enumerate(sub_inputs):
            idx = n + k
            label = f"[s{k}]"
            dur = c.end - c.start
            # each subtitle image only exists for its cue: shift it to the cue start
            filters.append(f"[{idx}:v]format=rgba,fade=t=in:st=0:d=0.15:alpha=1,"
                           f"fade=t=out:st={max(0.0, dur - 0.15):.3f}:d=0.15:alpha=1,"
                           f"setpts=PTS+{c.start:.3f}/TB[sub{k}]")
            filters.append(f"{cur}[sub{k}]overlay=0:0:eof_action=pass:"
                           f"enable='between(t,{c.start:.3f},{c.end:.3f})'{label}")
            cur = label
        filters.append(f"{cur}format=yuv420p[vout]")
        args += ["-filter_complex", ";".join(filters), "-map", "[vout]", "-map", f"{audio_idx}:a",
                 "-c:v", "libx264", "-preset", self.preset, "-crf", str(self.crf), "-r", str(FPS),
                 "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
                 "-t", f"{total_seconds:.3f}", "-movflags", "+faststart", str(out)]
        log.info("Assembling %d scenes + %d subtitles -> %s", n, len(sub_inputs), out)
        run_ffmpeg(args, self.cancel_check)
        return out
