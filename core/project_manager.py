"""Episode folder layout and JSON project files."""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class EpisodePaths:
    root: Path

    def __post_init__(self) -> None:
        for d in (self.characters, self.scenes, self.dialogue_audio, self.narration_audio, self.music_audio,
                  self.sfx_audio, self.renders, self.logs, self.temp):
            d.mkdir(parents=True, exist_ok=True)

    @property
    def final_video(self) -> Path:
        return self.root / "final_cartoon.mp4"

    @property
    def srt(self) -> Path:
        return self.root / "subtitles.srt"

    @property
    def project_json(self) -> Path:
        return self.root / "project.json"

    @property
    def scene_json(self) -> Path:
        return self.root / "scene_data.json"

    @property
    def characters_json(self) -> Path:
        return self.root / "characters.json"

    @property
    def characters(self) -> Path:
        return self.root / "characters"

    @property
    def scenes(self) -> Path:
        return self.root / "scenes"

    @property
    def dialogue_audio(self) -> Path:
        return self.root / "audio" / "dialogue"

    @property
    def narration_audio(self) -> Path:
        return self.root / "audio" / "narration"

    @property
    def music_audio(self) -> Path:
        return self.root / "audio" / "music"

    @property
    def sfx_audio(self) -> Path:
        return self.root / "audio" / "sound_effects"

    @property
    def master_audio(self) -> Path:
        return self.root / "audio" / "master_mix.wav"

    @property
    def renders(self) -> Path:
        return self.root / "renders"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def temp(self) -> Path:
        return self.root / "temp"

    def scene_blend(self, sid: int) -> Path:
        return self.scenes / f"scene_{sid:03d}.blend"

    def scene_frames(self, sid: int) -> Path:
        return self.renders / f"scene_{sid:03d}"

    def ai_clip(self, sid: int) -> Path:
        return self.renders / f"scene_{sid:03d}_ai.mp4"


class ProjectManager:
    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)

    def new_episode(self, name: str | None, hint: str = "cartoon") -> EpisodePaths:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if name:
            slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_") or "episode"
            return EpisodePaths(self.output_dir / slug)
        base = re.sub(r"[^a-z0-9]+", "_", hint.lower()).strip("_") or "cartoon"
        for i in range(1, 1000):
            p = self.output_dir / f"{base}_episode_{i:03d}"
            if not p.exists():
                return EpisodePaths(p)
        return EpisodePaths(self.output_dir / f"{base}_{datetime.now():%Y%m%d_%H%M%S}")

    @staticmethod
    def write_json(path: Path, data) -> None:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    @staticmethod
    def read_json(path: Path):
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def save_project(name: str, script: str, settings) -> Path:
        """Reopenable project file (script + settings) in the projects/ folder."""
        from utils.config import PROJECT_ROOT

        path = PROJECT_ROOT / "projects" / f"{name}.leo.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"format": "leo-project-1", "script": script,
                "settings": {"quality": settings.quality, "output_dir": str(settings.output_dir),
                             "episode_name": name, "voice_backend": settings.voice_backend, "music": settings.music,
                             "render_engine": settings.render_engine, "comfy_url": settings.comfy_url}}
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    @staticmethod
    def lock(root: Path) -> bool:
        """Claim an episode folder for one generation. False if another live process holds it
        (two runs in one folder would delete each other's frames)."""
        import os

        import psutil

        root.mkdir(parents=True, exist_ok=True)
        lock = root / ".generation.lock"
        try:
            pid = int(lock.read_text().strip())
            if pid != os.getpid() and psutil.pid_exists(pid):
                return False
        except (OSError, ValueError):
            pass  # no lock, or a stale/corrupt one left by a crash or power loss
        lock.write_text(str(os.getpid()))
        return True

    @staticmethod
    def unlock(root: Path) -> None:
        (root / ".generation.lock").unlink(missing_ok=True)

    @staticmethod
    def cleanup_temp(ep: EpisodePaths) -> None:
        shutil.rmtree(ep.temp, ignore_errors=True)
        ep.temp.mkdir(parents=True, exist_ok=True)
