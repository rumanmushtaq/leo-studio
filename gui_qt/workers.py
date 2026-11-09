"""Background jobs for the Qt UI. Workers talk to widgets only through signals."""
from __future__ import annotations

import threading
import traceback
from typing import Callable

from PySide6.QtCore import QThread, Signal

from core.generation_controller import GenerationController, GenerationResult, Progress
from utils.config import GenerationSettings
from utils.logger import get_logger

log = get_logger("ui")


class GenerationWorker(QThread):
    """Runs the full script -> MP4 pipeline."""

    progress = Signal(object)  # Progress
    finished_result = Signal(object)  # GenerationResult

    def __init__(self, settings: GenerationSettings, script: str, controller_factory=GenerationController):
        super().__init__()
        self.settings = settings
        self.script = script
        self.cancel_event = threading.Event()
        self._factory = controller_factory

    def run(self) -> None:
        try:
            ctrl = self._factory(self.settings, on_progress=self.progress.emit, cancel_event=self.cancel_event)
            res = ctrl.run(self.script)
        except Exception as exc:  # the controller reports its own errors; this is a last resort
            log.error("Generation crashed: %s", traceback.format_exc())
            res = GenerationResult(ok=False, error=str(exc))
        self.finished_result.emit(res)

    def cancel(self) -> None:
        self.cancel_event.set()


class TaskWorker(QThread):
    """Runs ``fn(progress)``; ``progress(fraction, message)`` is forwarded as a signal."""

    progress = Signal(float, str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[[Callable[[float, str], None]], object]):
        super().__init__()
        self.fn = fn

    def run(self) -> None:
        try:
            self.done.emit(self.fn(lambda f, m: self.progress.emit(float(f), str(m))))
        except Exception as exc:  # shown to the user by the page that started the task
            log.warning("Task failed: %s", traceback.format_exc())
            self.failed.emit(str(exc) or exc.__class__.__name__)


__all__ = ["GenerationWorker", "TaskWorker", "Progress", "GenerationResult"]
