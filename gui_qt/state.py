"""Shared studio state: settings, current script, open episode, the running job."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from core.character_manager import CharacterRegistry
from core.script_parser import ScriptParser
from core.scene_manager import SceneManager
from gui_qt.episodes import Episode, load_episode
from gui_qt.workers import GenerationWorker
from models.hardware_detector import detect
from utils import user_prefs
from utils.config import ASSETS_DIR, OUTPUT_DIR, PROJECT_ROOT, GenerationSettings

SAMPLE_SCRIPT = ASSETS_DIR / "scripts" / "leo_episode_001.txt"
PROJECTS_DIR = PROJECT_ROOT / "projects"


def parse_script(text: str):
    """Parsed + enriched script (scenes, characters, actions), or the parser report on errors."""
    parsed = ScriptParser().parse(text)
    if parsed.report.ok:
        SceneManager(CharacterRegistry()).enrich(parsed)
    return parsed


def looks_like_script(text: str) -> bool:
    p = ScriptParser().parse(text)
    return p.report.ok and len(p.all_dialogue_events()) >= 3


class StudioState(QObject):
    script_changed = Signal(str)
    episode_changed = Signal(object)  # Episode | None
    job_started = Signal(str)  # what is running ("generate", "write", ...)
    job_progress = Signal(object)  # Progress
    job_finished = Signal(object)  # GenerationResult
    settings_changed = Signal()
    toast = Signal(str)
    navigate = Signal(str)  # page key

    def __init__(self, hardware=None, worker_factory=GenerationWorker):
        super().__init__()
        self.hw = hardware or detect()
        prefs = user_prefs.load()
        self.settings = GenerationSettings(output_dir=Path(prefs.get("output_dir", OUTPUT_DIR)))
        self.settings.quality = prefs.get("quality", self.hw.recommended_quality)
        self.settings.voice_backend = prefs.get("voice_backend", self.settings.voice_backend)
        self.settings.music = prefs.get("music", self.settings.music)
        self.settings.render_engine = prefs.get("render_engine", self.settings.render_engine)
        self.settings.comfy_url = prefs.get("comfy_url", self.settings.comfy_url)
        self.settings.ai_backgrounds = prefs.get("ai_backgrounds", self.settings.ai_backgrounds)
        self.script = ""
        self.episode: Episode | None = None
        self.worker: GenerationWorker | None = None
        self.busy_with: str | None = None
        self.last_result = None
        self._worker_factory = worker_factory

    # ------------------------------------------------------------- settings
    def save_settings(self) -> None:
        s = self.settings
        user_prefs.save(output_dir=str(s.output_dir), quality=s.quality, voice_backend=s.voice_backend,
                        music=s.music, render_engine=s.render_engine, comfy_url=s.comfy_url,
                        ai_backgrounds=s.ai_backgrounds)
        self.settings_changed.emit()

    # --------------------------------------------------------------- script
    def set_script(self, text: str, emit: bool = True) -> None:
        self.script = text
        if emit:
            self.script_changed.emit(text)

    def load_sample(self) -> None:
        self.set_script(SAMPLE_SCRIPT.read_text(encoding="utf-8"))

    def open_file(self, path: Path) -> None:
        path = Path(path)
        if path.name.endswith(".leo.json"):
            proj = json.loads(path.read_text(encoding="utf-8"))
            st = proj.get("settings", {})
            for key in ("quality", "voice_backend", "music", "render_engine", "comfy_url"):
                if key in st:
                    setattr(self.settings, key, st[key])
            if st.get("output_dir"):
                self.settings.output_dir = Path(st["output_dir"])
            self.settings.episode_name = st.get("episode_name")
            self.set_script(proj.get("script", ""))
            self.settings_changed.emit()
        else:
            self.settings.episode_name = None
            self.set_script(path.read_text(encoding="utf-8"))

    def save_project(self, path: Path) -> Path:
        s = self.settings
        data = {"format": "leo-project-1", "script": self.script,
                "settings": {"quality": s.quality, "output_dir": str(s.output_dir), "episode_name": s.episode_name,
                             "voice_backend": s.voice_backend, "music": s.music,
                             "render_engine": s.render_engine, "comfy_url": s.comfy_url}}
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    # -------------------------------------------------------------- episode
    def open_episode(self, root: Path | None) -> None:
        self.episode = load_episode(root) if root else None
        if self.episode and self.episode.script:
            self.settings.episode_name = self.episode.name
            self.set_script(self.episode.script)
        self.episode_changed.emit(self.episode)

    def refresh_episode(self) -> None:
        if self.episode:
            self.episode = load_episode(self.episode.root)
            self.episode_changed.emit(self.episode)

    # ------------------------------------------------------------ generation
    @property
    def busy(self) -> bool:
        return self.busy_with is not None

    def generate(self, script: str | None = None, episode_name: str | None = None) -> str | None:
        """Start the pipeline; returns an error message instead of starting when not possible."""
        if self.busy:
            return "Another job is still running."
        text = (script if script is not None else self.script).strip()
        parsed = ScriptParser().parse(text)
        if not parsed.report.ok:
            return "The script has a problem: " + " ".join(parsed.report.errors)
        if script is not None:
            self.set_script(text)
        self.settings.episode_name = episode_name
        self.worker = self._worker_factory(self.settings, text)
        self.worker.progress.connect(self.job_progress)
        self.worker.finished_result.connect(self._on_finished)
        self.busy_with = "generate"
        self.job_started.emit("generate")
        self.worker.start()
        return None

    def cancel(self) -> None:
        if self.worker:
            self.worker.cancel()

    def _on_finished(self, res) -> None:
        self.busy_with = None
        self.last_result = res
        if self.worker:
            self.worker.wait(2000)
        self.worker = None
        if res.episode_dir:
            self.episode = load_episode(res.episode_dir)
            self.episode_changed.emit(self.episode)
        self.job_finished.emit(res)
