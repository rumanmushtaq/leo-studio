"""Render one scene with the AI video pipeline on a ComfyUI server.

Per shot:  Blender keyframe --(Flux img2img restyle)--> styled keyframe
           --(Wan 2.2 image-to-video, chained 5 s segments)--> moving clip
           --(LatentSync, only for shots with visible speakers)--> lip-synced clip
Shots are trimmed/padded to their exact frame ranges so the scene clip has exactly the
frame count the timeline planned, keeping dialogue, music and subtitles in sync.
Every ComfyUI result is cached by a hash of its inputs, so a crash or cancel resumes.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from engines.ai_video import workflows
from engines.ai_video.comfy_client import ComfyClient, ComfyError
from engines.ai_video.shot_planner import NEGATIVE, AIShot, segments
from utils.audio_utils import read_audio, write_wav
from utils.config import AUDIO_SAMPLE_RATE, FPS, OUTPUT_HEIGHT, OUTPUT_WIDTH
from utils.ffmpeg_utils import run_ffmpeg
from utils.logger import get_logger

log = get_logger("ai_video")


@dataclass
class AISettings:
    server: str = "http://127.0.0.1:8188"
    width: int = 1280          # Wan 2.2 5B native 720p-class size (multiples of 32)
    height: int = 704
    clip_frames: int = 121     # ~5 s at 24 fps (Wan lengths are 4k+1)
    steps: int = 20
    denoise: float = 0.55      # how strongly Flux repaints the Blender keyframe
    lipsync: bool = True


class AIVideoRenderer:
    def __init__(self, settings: AISettings, work_dir: Path, cancel_check: Callable[[], bool] | None = None,
                 client: ComfyClient | None = None):
        self.s = settings
        self.work = Path(work_dir)
        self.work.mkdir(parents=True, exist_ok=True)
        self.cache = self.work / "cache"
        self.cache.mkdir(exist_ok=True)
        self.cancel_check = cancel_check
        self.client = client or ComfyClient(settings.server)
        self.templates = {k: workflows.load(k) for k in ("restyle", "i2v", "lipsync")}
        self.lipsync_ok: bool | None = None
        self.report: dict = {"shots": 0, "segments": 0, "lipsynced": 0, "lipsync_skipped_reason": None}

    # ---------------------------------------------------------------- helpers
    def _cached_run(self, kind: str, wf: dict, inputs: list[Path], stem: str) -> Path:
        h = hashlib.sha256(json.dumps(wf, sort_keys=True).encode())
        for p in inputs:
            h.update(Path(p).read_bytes())
        key = h.hexdigest()[:20]
        for hit in self.cache.glob(f"{kind}_{key}.*"):
            return hit
        out = self.client.run(wf, self.cache, f"{kind}_{key}", cancel_check=self.cancel_check)
        log.info("%s done: %s", kind, stem)
        return out

    def _upload(self, path: Path) -> str:
        return self.client.upload(path)

    def _last_frame(self, clip: Path, dest: Path) -> Path:
        run_ffmpeg(["-sseof", "-0.1", "-i", str(clip), "-frames:v", "1", "-update", "1", str(dest)], self.cancel_check)
        return dest

    def _segment_audio(self, shot: AIShot, seg_start_s: float, seg_len_s: float, dest: Path) -> Path | None:
        n = int(seg_len_s * AUDIO_SAMPLE_RATE)
        buf = np.zeros(n, dtype=np.float32)
        used = False
        for lip in shot.lipsync:
            data = read_audio(Path(lip["audio"]))
            at = int((lip["offset_s"] - seg_start_s) * AUDIO_SAMPLE_RATE)
            a0, b0 = max(0, at), max(0, -at)
            m = min(n - a0, len(data) - b0)
            if m > 0:
                buf[a0:a0 + m] += data[b0:b0 + m]
                used = True
        if not used:
            return None
        write_wav(dest, buf)
        return dest

    def _check_lipsync(self) -> bool:
        if self.lipsync_ok is None:
            if not self.s.lipsync:
                self.lipsync_ok = False
                self.report["lipsync_skipped_reason"] = "disabled in settings"
            else:
                missing = self.client.missing_nodes(self.templates["lipsync"])
                self.lipsync_ok = not missing
                if missing:
                    self.report["lipsync_skipped_reason"] = "ComfyUI lacks nodes: " + ", ".join(missing)
                    log.warning("AI lip-sync unavailable (%s); clips keep the generated mouth motion",
                                self.report["lipsync_skipped_reason"])
        return bool(self.lipsync_ok)

    # ------------------------------------------------------------------ shot
    def render_shot(self, shot: AIShot, keyframe: Path) -> Path:
        tag = f"s{shot.scene_id:02d}_shot{shot.index:02d}"
        styled = self._cached_run("restyle", workflows.fill(
            self.templates["restyle"], IMAGE=self._upload(keyframe), PROMPT=shot.image_prompt, SEED=shot.seed,
            WIDTH=self.s.width, HEIGHT=self.s.height, DENOISE=self.s.denoise), [keyframe], tag)
        start_img = styled
        pieces: list[Path] = []
        offset = 0
        for k, length in enumerate(segments(shot.frames, self.s.clip_frames)):
            clip = self._cached_run("i2v", workflows.fill(
                self.templates["i2v"], IMAGE=self._upload(start_img), PROMPT=shot.motion_prompt, NEGATIVE=NEGATIVE,
                SEED=shot.seed + k, WIDTH=self.s.width, HEIGHT=self.s.height, FRAMES=length, FPS=FPS,
                STEPS=self.s.steps), [start_img], f"{tag}_seg{k}")
            if shot.lipsync and self._check_lipsync():
                audio = self._segment_audio(shot, offset / FPS, length / FPS,
                                            self.work / f"{tag}_seg{k}_voice.wav")
                if audio is not None:
                    try:
                        clip = self._cached_run("lipsync", workflows.fill(
                            self.templates["lipsync"], VIDEO=self._upload(clip), AUDIO=self._upload(audio),
                            SEED=shot.seed, FPS=FPS), [clip, audio], f"{tag}_seg{k}")
                        self.report["lipsynced"] += 1
                    except ComfyError as exc:
                        if "cancelled" in str(exc):
                            raise
                        log.warning("Lip-sync failed for %s seg %d: %s (keeping un-synced clip)", tag, k, exc)
            pieces.append(clip)
            self.report["segments"] += 1
            offset += length - 1
            start_img = self._last_frame(clip, self.work / f"{tag}_seg{k}_last.png")
        self.report["shots"] += 1
        return self._fit(pieces, shot.frames, self.work / f"{tag}.mp4")

    def _fit(self, pieces: list[Path], n_frames: int, out: Path) -> Path:
        """Join chained segments (dropping each repeated first frame), scale to 1280x720 at 24 fps,
        and cut/pad to exactly ``n_frames``."""
        args: list[str] = []
        for p in pieces:
            args += ["-i", str(p)]
        parts = []
        for i in range(len(pieces)):
            trim = "trim=start_frame=1," if i > 0 else ""
            parts.append(f"[{i}:v]{trim}setpts=PTS-STARTPTS,fps={FPS},scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:"
                         f"force_original_aspect_ratio=increase,crop={OUTPUT_WIDTH}:{OUTPUT_HEIGHT},setsar=1[v{i}]")
        chain = "".join(f"[v{i}]" for i in range(len(pieces)))
        flt = ";".join(parts) + f";{chain}concat=n={len(pieces)}:v=1:a=0,tpad=stop_mode=clone:stop_duration=10[out]"
        run_ffmpeg([*args, "-filter_complex", flt, "-map", "[out]", "-frames:v", str(n_frames), "-an",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", "-r", str(FPS),
                    str(out)], self.cancel_check)
        return out

    # ----------------------------------------------------------------- scene
    def render_scene(self, shots: list[AIShot], keyframes: dict[int, Path], n_frames: int, out: Path,
                     on_shot: Callable[[int, int], None] | None = None) -> Path:
        clips = []
        for k, shot in enumerate(shots, start=1):
            clips.append((shot, self.render_shot(shot, keyframes[shot.index])))
            if on_shot:
                on_shot(k, len(shots))
        lst = self.work / f"scene_{shots[0].scene_id:02d}_concat.txt"
        lst.write_text("".join(f"file '{c.resolve().as_posix()}'\n" for _, c in clips), encoding="utf-8")
        run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(lst), "-vf",
                    "tpad=stop_mode=clone:stop_duration=10", "-frames:v", str(n_frames), "-c:v", "libx264",
                    "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", "-r", str(FPS), str(out)],
                   self.cancel_check)
        return out
