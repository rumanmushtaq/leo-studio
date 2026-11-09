"""Host-side control of background Blender processes (no bpy import).

Runs ``blender -b`` with one of the ``run_*.py`` entry scripts, streams stdout
for structured progress lines (``LEO_PROGRESS``, ``LEO_FRAME``), supports
cancellation (kills the process) and keeps a log file per run.
"""
from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from utils.config import PROC_KW, PROJECT_ROOT, find_blender
from utils.logger import get_logger

log = get_logger("blender")
BLENDER_DIR = PROJECT_ROOT / "blender"


class BlenderError(RuntimeError):
    pass


class Cancelled(RuntimeError):
    pass


class BlenderManager:
    def __init__(self, blender_path: str | None = None, cancel_event: threading.Event | None = None):
        self.blender = blender_path or find_blender()
        if not self.blender:
            raise BlenderError("Blender 4.x was not found. Install Blender 4.5 LTS from blender.org "
                               "(see README) or set LEO_BLENDER=/path/to/blender.")
        self.cancel_event = cancel_event or threading.Event()

    def run(self, args: list[str], log_path: Path, on_line: Callable[[str], None] | None = None,
            idle_timeout: float | None = None) -> list[str]:
        """Run Blender with ``args``; return its stdout lines. Raises on failure/cancel.

        ``idle_timeout``: kill Blender if it prints nothing for that many seconds (hang watchdog).
        """
        cmd = [self.blender, "-b", *args]
        log_path.parent.mkdir(parents=True, exist_ok=True)
        tail: list[str] = []
        with open(log_path, "a", encoding="utf-8") as lf:
            lf.write("$ " + " ".join(cmd) + "\n")
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    cwd=str(PROJECT_ROOT), **PROC_KW)
            self._last_output = time.monotonic()
            self._stalled = False
            killer = threading.Thread(target=self._watch_cancel, args=(proc, idle_timeout), daemon=True)
            killer.start()
            assert proc.stdout is not None
            for line in proc.stdout:
                self._last_output = time.monotonic()
                lf.write(line)
                line = line.rstrip("\n")
                tail.append(line)
                if len(tail) > 400:
                    tail = tail[-200:]
                if on_line and line.startswith("LEO_"):
                    on_line(line)
            proc.wait()
        if self.cancel_event.is_set():
            raise Cancelled("Generation cancelled")
        if self._stalled:
            raise BlenderError(f"Blender produced no output for {idle_timeout:.0f} s and was stopped. See {log_path}")
        errors = [l for l in tail if re.search(r"Traceback|Error:|error:|EXCEPTION", l)]
        if proc.returncode != 0 or any("Traceback" in l for l in tail):
            msg = "\n".join(errors[-8:] or tail[-15:])
            raise BlenderError(f"Blender failed (exit {proc.returncode}). See {log_path}\n{msg}")
        return tail

    def _watch_cancel(self, proc: subprocess.Popen, idle_timeout: float | None = None) -> None:
        while proc.poll() is None:
            if self.cancel_event.wait(0.3):
                proc.kill()
                return
            if idle_timeout and time.monotonic() - self._last_output > idle_timeout:
                log.warning("Blender silent for %.0f s; stopping it", idle_timeout)
                self._stalled = True
                proc.kill()
                return

    def run_script(self, script: str, job: dict, job_path: Path, log_path: Path,
                   on_line: Callable[[str], None] | None = None, blend_file: Path | None = None,
                   extra: list[str] | None = None) -> list[str]:
        job_path.parent.mkdir(parents=True, exist_ok=True)
        job_path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        args = [str(blend_file)] if blend_file else ["--factory-startup"]
        args += ["-P", str(BLENDER_DIR / script), "--", str(job_path), *(extra or [])]
        return self.run(args, log_path, on_line)
