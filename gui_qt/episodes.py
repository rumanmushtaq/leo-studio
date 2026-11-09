"""Find finished/partial episodes in the output folder and describe them (no Qt here)."""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from utils.config import PROC_KW, find_ffmpeg


@dataclass
class SceneInfo:
    id: int
    title: str
    location: str
    start: float
    duration: float
    characters: list[str]
    first_line: str = ""
    frames_done: int = 0
    frame_count: int = 0

    @property
    def rendered(self) -> bool:
        return self.frame_count > 0 and self.frames_done >= self.frame_count


@dataclass
class Episode:
    root: Path
    name: str
    video: Path | None
    modified: datetime
    duration: float = 0.0
    scenes: list[SceneInfo] = field(default_factory=list)
    script: str = ""
    ok: bool = False

    @property
    def thumbnail(self) -> Path:
        return self.root / "thumbnail.jpg"

    def frame_path(self, scene_id: int, frame: int) -> Path:
        return self.root / "renders" / f"scene_{scene_id:03d}" / f"frame_{frame:04d}.jpg"

    def scene_thumb(self, scene: SceneInfo) -> Path | None:
        if scene.frames_done <= 0:
            return None
        # a frame a third into the scene: characters have usually walked in by then
        f = min(scene.frames_done - 1, max(0, scene.frame_count // 3))
        p = self.frame_path(scene.id, f)
        return p if p.exists() else None


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def load_episode(root: Path) -> Episode | None:
    root = Path(root)
    timeline = _read_json(root / "scene_data.json")
    project = _read_json(root / "project.json") or {}
    if timeline is None and not (root / "parsed_script.json").exists():
        return None
    video = root / "final_cartoon.mp4"
    ep = Episode(root=root, name=root.name, video=video if video.exists() else None,
                 modified=datetime.fromtimestamp(root.stat().st_mtime), ok=bool(project.get("ok")))
    for proj in (root.parent.parent / "projects" / f"{root.name}.leo.json",
                 Path(__file__).resolve().parent.parent / "projects" / f"{root.name}.leo.json"):
        data = _read_json(proj)
        if data:
            ep.script = data.get("script", "")
            break
    if timeline:
        ep.duration = float(timeline.get("total_seconds", 0.0))
        for s in timeline.get("scenes", []):
            frames_dir = root / "renders" / f"scene_{s['id']:03d}"
            done = len(list(frames_dir.glob("frame_*.jpg"))) if frames_dir.exists() else 0
            first = next((d.get("text", "") for d in s.get("dialogues", [])), "")
            ep.scenes.append(SceneInfo(id=s["id"], title=s.get("title", f"Scene {s['id']}"),
                                       location=s.get("location", ""), start=float(s.get("start_time", 0.0)),
                                       duration=float(s.get("duration", 0.0)),
                                       characters=[c["id"] for c in s.get("characters", [])],
                                       first_line=first, frames_done=done, frame_count=int(s.get("frame_count", 0))))
    if video.exists() and video.stat().st_mtime > ep.modified.timestamp():
        ep.modified = datetime.fromtimestamp(video.stat().st_mtime)
    return ep


def find_episodes(output_dir: Path) -> list[Episode]:
    output_dir = Path(output_dir)
    if not output_dir.exists():
        return []
    eps = [e for d in output_dir.iterdir() if d.is_dir() and (e := load_episode(d))]
    return sorted(eps, key=lambda e: e.modified, reverse=True)


def make_thumbnail(ep: Episode) -> Path | None:
    """Cached JPEG for the gallery: a middle frame of the video, else a rendered frame."""
    out = ep.thumbnail
    if out.exists() and (ep.video is None or out.stat().st_mtime >= ep.video.stat().st_mtime):
        return out
    if ep.video:
        ff = find_ffmpeg()
        if ff:
            t = max(1.0, ep.duration * 0.4) if ep.duration else 10.0
            try:
                subprocess.run([ff, "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(ep.video),
                                "-frames:v", "1", "-vf", "scale=480:-2", str(out)],
                               timeout=60, check=True, capture_output=True, **PROC_KW)
                if out.exists():
                    return out
            except (OSError, subprocess.SubprocessError):
                pass
    for s in ep.scenes:
        p = ep.scene_thumb(s)
        if p:
            shutil.copyfile(p, out)
            return out
    return None


def scene_at(ep: Episode, seconds: float) -> SceneInfo | None:
    for s in reversed(ep.scenes):
        if seconds >= s.start:
            return s
    return ep.scenes[0] if ep.scenes else None


def clear_scene_frames(ep: Episode, scene_id: int) -> int:
    """Delete one scene's rendered frames so the next generation renders only that scene again."""
    d = ep.root / "renders" / f"scene_{scene_id:03d}"
    n = len(list(d.glob("frame_*.jpg"))) if d.exists() else 0
    shutil.rmtree(d, ignore_errors=True)
    for extra in (ep.root / "renders" / f"scene_{scene_id:03d}_ai.mp4",):
        extra.unlink(missing_ok=True)
    return n
