"""Host-side frame rendering of saved scene files with progress and fallback.

EEVEE (default) needs an OpenGL 4.3 capable GPU or iGPU (Intel UHD, AMD, NVIDIA
all work through Mesa/drivers). If Blender cannot create a GPU context — e.g.
a headless server without any GPU — rendering falls back to the Workbench
engine (still real 3D geometry, simpler studio lighting) and the fallback is
reported. Cycles can be chosen explicitly for high quality / CUDA systems.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from blender.blender_manager import BLENDER_DIR, BlenderError, BlenderManager
from utils.logger import get_logger

log = get_logger("render")

GPU_CONTEXT_ERRORS = ("Unable to initialize GPU", "GPU backend", "OpenGL", "EGL", "failed to create")


class RenderManager:
    def __init__(self, blender: BlenderManager, quality: str = "standard", engine: str = "BLENDER_EEVEE_NEXT"):
        self.blender = blender
        self.quality = quality
        self.engine = engine
        self.fallback_used: str | None = None

    def count_done(self, frames_dir: Path) -> int:
        return len(list(frames_dir.glob("frame_*.jpg")))

    def render_scene(self, blend: Path, frames_dir: Path, n_frames: int, log_path: Path,
                     on_frame: Callable[[int, int], None] | None = None) -> int:
        frames_dir.mkdir(parents=True, exist_ok=True)
        done0 = self.count_done(frames_dir)
        if done0 >= n_frames:
            if on_frame:
                on_frame(n_frames, n_frames)
            return n_frames
        counter = {"n": done0}

        def handle(line: str) -> None:
            if line.startswith("LEO_FRAME") and on_frame:
                counter["n"] += 1
                on_frame(min(counter["n"], n_frames), n_frames)

        engine = self.fallback_used or self.engine
        try:
            self._run(blend, engine, log_path, handle)
        except BlenderError:
            if self.count_done(frames_dir) >= n_frames:
                log.warning("%s: Blender exited abnormally after writing all %d frames; continuing.",
                            blend.name, n_frames)
            else:
                raise
        done = self.count_done(frames_dir)
        if done < n_frames:
            raise BlenderError(f"{blend.name}: only {done}/{n_frames} frames rendered. See {log_path}")
        return done

    def _run(self, blend: Path, engine: str, log_path: Path, handle) -> None:
        try:
            self.blender.run([str(blend), "-P", str(BLENDER_DIR / "run_render_scene.py"), "--", engine,
                              self.quality], log_path, handle, idle_timeout=600)
        except BlenderError as exc:
            if engine == "BLENDER_EEVEE_NEXT" and any(k in str(exc) for k in GPU_CONTEXT_ERRORS):
                log.warning("EEVEE could not start (%s); falling back to Workbench.", str(exc).splitlines()[0])
                self.fallback_used = "BLENDER_WORKBENCH"
                self.blender.run([str(blend), "-P", str(BLENDER_DIR / "run_render_scene.py"), "--",
                                  "BLENDER_WORKBENCH", self.quality], log_path, handle, idle_timeout=600)
            else:
                raise
