"""End-to-end pipeline: script -> 3D animated MP4.

Runs in a worker thread (GUI) or directly (CLI/tests). Progress is reported
from real completed work: each stage has a weight and a done/total count
(characters built, lines voiced, frames rendered...).
"""
from __future__ import annotations

import shutil
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from blender.blender_manager import BlenderManager, Cancelled
from blender.render_manager import RenderManager
from core.character_manager import CharacterRegistry
from core.project_manager import EpisodePaths, ProjectManager
from core.scene_manager import SceneManager
from core.script_parser import ParsedScript, ScriptParser
from core.timeline_manager import DialogueAudio, TimelineManager
from engines.lipsync_engine import lipsync_curves
from engines.sound_engine import SoundMixer, get_music
from engines.subtitle_engine import SubtitleEngine
from engines.video_assembler import VideoAssembler
from engines.voice_engine import VoiceEngine
from models.hardware_detector import detect
from utils.audio_utils import write_wav
from utils.config import CHARACTER_LIBRARY, FPS, GenerationSettings
from utils.logger import add_file_handler, get_logger, remove_handler
from utils.validators import check_frames, verify_video

log = get_logger("pipeline")

STAGES = [
    ("parse", "Analysing script", 1),
    ("characters", "Building 3D characters", 6),
    ("voices", "Generating Urdu/English voices", 8),
    ("lipsync", "Computing lip-sync", 1),
    ("timeline", "Directing scenes and cameras", 1),
    ("backgrounds", "Painting backgrounds (AI)", 3),
    ("scenes", "Building 3D scenes in Blender", 6),
    ("render", "Rendering frames (EEVEE)", 66),
    ("audio", "Mixing music, effects and dialogue", 4),
    ("subtitles", "Rendering Urdu subtitles", 1),
    ("assemble", "Encoding final MP4", 5),
    ("verify", "Verifying video", 1),
]


@dataclass
class Progress:
    stage: str
    label: str
    percent: float
    stage_done: int = 0
    stage_total: int = 0
    scene: int | None = None
    scene_count: int = 0
    message: str = ""


@dataclass
class GenerationResult:
    ok: bool
    video: Path | None = None
    episode_dir: Path | None = None
    error: str | None = None
    report: dict = field(default_factory=dict)


class GenerationController:
    def __init__(self, settings: GenerationSettings, on_progress: Callable[[Progress], None] | None = None,
                 cancel_event: threading.Event | None = None):
        self.settings = settings
        self.on_progress = on_progress or (lambda p: None)
        self.cancel_event = cancel_event or threading.Event()
        self._weights = {k: w for k, _, w in STAGES}
        self._labels = {k: label for k, label, _ in STAGES}
        self._frac = {k: 0.0 for k, _, _ in STAGES}
        self.scene_count = 0
        self._voice_used: dict[str, int] = {}
        self._ai_reports: dict[int, dict] = {}
        self._render_seconds = 0.0
        self._backdrops: dict[str, str] = {}
        self._render_frames = 0

    # --------------------------------------------------------------- progress
    def _report(self, stage: str, done: int, total: int, scene: int | None = None, message: str = "") -> None:
        self._frac[stage] = (done / total) if total else 1.0
        pct = 100.0 * sum(self._weights[k] * f for k, f in self._frac.items()) / sum(self._weights.values())
        self.on_progress(Progress(stage, self._labels[stage], round(pct, 1), done, total, scene, self.scene_count,
                                  message))

    def _check_cancel(self) -> None:
        if self.cancel_event.is_set():
            raise Cancelled("Generation cancelled by user")

    # --------------------------------------------------------------- pipeline
    def parse(self, text: str, registry: CharacterRegistry) -> ParsedScript:
        parsed = ScriptParser().parse(text)
        if parsed.report.ok:
            SceneManager(registry).enrich(parsed)
        return parsed

    def run(self, script_text: str) -> GenerationResult:
        st = self.settings
        handler = None
        ep: EpisodePaths | None = None
        t_start = time.time()
        try:
            hw = detect()
            if not hw.blender_path:
                raise RuntimeError(hw.warnings[0])
            if not hw.ffmpeg_path:
                raise RuntimeError("FFmpeg not found. Install it: sudo apt install ffmpeg")
            if st.render_engine == "ai":  # fail fast: hours of work depend on the GPU server
                from engines.ai_video.comfy_client import ComfyClient

                log.info("AI video server: %s", ComfyClient(st.comfy_url).describe())
            registry = CharacterRegistry()
            self.registry = registry
            self._report("parse", 0, 1, message="Reading script")
            parsed = self.parse(script_text, registry)
            if not parsed.report.ok:
                raise ValueError("Script problem: " + " ".join(parsed.report.errors))
            self.scene_count = len(parsed.scenes)
            hero = next((c for s in parsed.scenes for c in s.characters
                         if registry.get_or_create(c).role == "hero"), None)
            ep = ProjectManager(st.output_dir).new_episode(st.episode_name, hint=hero or "cartoon")
            handler = add_file_handler(ep.logs / "generation.log")
            log.info("Episode folder: %s", ep.root)
            for line in hw.summary_lines():
                log.info("Hardware: %s", line)
            ProjectManager.write_json(ep.root / "parsed_script.json", parsed.to_dict())
            ProjectManager.save_project(ep.root.name, script_text, st)
            self._report("parse", 1, 1, message=f"{len(parsed.scenes)} scenes, "
                                                 f"{len(parsed.all_dialogue_events())} lines")

            blender = BlenderManager(hw.blender_path, self.cancel_event)
            char_ids = self._build_characters(parsed, registry, blender, ep)
            audio = self._voices(parsed, registry, ep)
            self._check_cancel()

            self._report("timeline", 0, 1)
            timeline = TimelineManager(registry).build(parsed, audio)
            ProjectManager.write_json(ep.scene_json, timeline)
            self._report("timeline", 1, 1, message=f"{timeline['total_seconds']:.1f} s episode")

            self._backdrops = self._paint_backgrounds(timeline)
            renderer = RenderManager(blender, st.quality,
                                     engine="CYCLES" if st.quality == "high" and st.use_gpu else "BLENDER_EEVEE_NEXT")
            self._scenes_and_render(timeline, char_ids, blender, renderer, ep)

            self._report("audio", 0, 1)
            mix_report = SoundMixer(music=st.music).mix(timeline, ep.master_audio, ep.sfx_audio)
            if st.music:
                write_wav(ep.music_audio / "background_music.wav", get_music(min(30.0, timeline["total_seconds"])))
            self._report("audio", 1, 1)
            self._check_cancel()

            self._report("subtitles", 0, 1)
            subs = SubtitleEngine()
            names = {cid: s.name for cid, s in registry.characters.items()}
            cues = subs.cues(timeline, names)
            subs.write_srt(cues, ep.srt)
            subs.render_all(cues, ep.temp / "subtitles")
            self._report("subtitles", 1, 1)

            video = self._assemble(timeline, cues, ep)
            self._report("verify", 0, 1)
            expected_frames = round(timeline["total_seconds"] * FPS)
            check = verify_video(video, expected_seconds=timeline["total_seconds"], expected_frames=expected_frames)
            dialogue_ids = [TimelineManager.dialogue_id(s.id, i) for s in parsed.scenes
                            for i, e in enumerate(s.events) if e.kind in ("dialogue", "narration")]
            timeline_ids = [d["id"] for sd in timeline["scenes"] for d in sd["dialogues"]]
            if st.render_engine == "ai":
                from utils.ffmpeg_utils import probe

                frame_qc = {}
                for sd in timeline["scenes"]:
                    v = probe(ep.ai_clip(sd["id"]), count_frames=True).video
                    n = v.frames if v else 0
                    frame_qc[sd["id"]] = {"expected": sd["frame_count"], "found": n, "ok": n >= sd["frame_count"]}
            else:
                frame_qc = {sd["id"]: check_frames(ep.scene_frames(sd["id"]), sd["frame_count"])
                            for sd in timeline["scenes"]}
            check.checks["all_scenes_rendered"] = all(q["found"] >= q["expected"] for q in frame_qc.values())
            check.checks["no_corrupt_or_blank_frames"] = all(q["ok"] for q in frame_qc.values())
            check.details["frame_qc"] = {k: {kk: (len(v) if isinstance(v, list) else v) for kk, v in q.items()}
                                         for k, q in frame_qc.items()}
            check.checks["all_dialogue_accounted"] = (dialogue_ids == timeline_ids and len(cues) == len(dialogue_ids))
            check.ok = all(check.checks.values())
            self._report("verify", 1, 1)

            report = {
                "episode": ep.root.name, "video": str(video), "ok": check.ok, "checks": check.checks,
                "video_details": check.details, "decode_errors": check.errors,
                "scenes": [{"id": s["id"], "title": s["title"], "location": s["location"],
                            "frames": s["frame_count"], "characters": [c["id"] for c in s["characters"]],
                            "shots": [sh["type"] for sh in s["camera_shots"]]} for s in timeline["scenes"]],
                "dialogue_lines": len(dialogue_ids), "voice_backends": self._voice_used,
                "render_engine": ("ai_video(comfyui)" if st.render_engine == "ai" else
                                  renderer.fallback_used or renderer.engine), "quality": st.quality,
                "ai_video": self._ai_reports,
                "audio_mix": mix_report, "parse_warnings": parsed.report.warnings,
                "hardware": hw.to_dict(), "elapsed_seconds": round(time.time() - t_start, 1),
            }
            ProjectManager.write_json(ep.project_json, report)
            if not st.keep_temp:
                ProjectManager.cleanup_temp(ep)
            if not check.ok:
                failed = [k for k, v in check.checks.items() if not v]
                return GenerationResult(False, video, ep.root, f"Video verification failed: {', '.join(failed)}",
                                        report)
            if self._render_seconds and self._render_frames and st.render_engine == "blender":
                from utils.user_prefs import record_render_speed

                record_render_speed(st.quality, self._render_seconds / self._render_frames)
            log.info("Done in %.0f s: %s", time.time() - t_start, video)
            return GenerationResult(True, video, ep.root, None, report)
        except Cancelled as exc:
            log.warning("Cancelled")
            return GenerationResult(False, None, ep.root if ep else None, str(exc))
        except Exception as exc:  # surfaced to the GUI as a readable message
            log.error("Generation failed: %s\n%s", exc, traceback.format_exc())
            return GenerationResult(False, None, ep.root if ep else None, str(exc))
        finally:
            if handler:
                remove_handler(handler)

    # ---------------------------------------------------------------- stages
    def _build_characters(self, parsed: ParsedScript, registry: CharacterRegistry, blender: BlenderManager,
                          ep: EpisodePaths) -> dict[str, str]:
        needed = sorted({c for s in parsed.scenes for c in s.characters})
        todo = [c for c in needed if not registry.asset_is_current(c)]
        self._report("characters", 0, len(needed), message=f"{len(needed) - len(todo)} reused, {len(todo)} to build")
        done = len(needed) - len(todo)
        for c in todo:  # one Blender process per character keeps peak RAM low on 8 GB machines
            self._check_cancel()
            job = {"characters": [{"id": c, "spec": registry.characters[c].data,
                                   "blend_path": str(registry.asset_path(c)),
                                   "reference_path": str(CHARACTER_LIBRARY / f"{c}_reference.png")}],
                   "reference_size": 512}
            blender.run_script("run_build_characters.py", job, ep.temp / f"character_{c}_job.json",
                               ep.logs / "blender_characters.log")
            registry.mark_built(c)
            registry.save()
            done += 1
            self._report("characters", done, len(needed), message=registry.characters[c].name)
        registry.save()
        assets = {}
        for c in needed:
            src = registry.asset_path(c)
            shutil.copy2(src, ep.characters / src.name)
            ref = CHARACTER_LIBRARY / f"{c}_reference.png"
            if ref.exists():
                shutil.copy2(ref, ep.characters / ref.name)
            assets[c] = str(src)
        ProjectManager.write_json(ep.characters_json, {c: registry.characters[c].data for c in needed})
        self._report("characters", len(needed), len(needed))
        return assets

    def _voices(self, parsed: ParsedScript, registry: CharacterRegistry, ep: EpisodePaths
                ) -> dict[str, DialogueAudio]:
        st = self.settings
        engine = VoiceEngine(st.voice_backend, st.manual_audio_dir)
        lines = [(s, i, e) for s in parsed.scenes for i, e in enumerate(s.events) if e.kind in ("dialogue", "narration")]
        out: dict[str, DialogueAudio] = {}
        self._report("voices", 0, len(lines))
        try:
            for n, (s, i, e) in enumerate(lines, start=1):
                self._check_cancel()
                did = TimelineManager.dialogue_id(s.id, i)
                spec = registry.get_or_create(e.speaker_id or "narrator")
                folder = ep.narration_audio if e.kind == "narration" else ep.dialogue_audio
                res = engine.synthesize(did, n, e.text, e.language, spec.voice, folder / f"{did}_{spec.id}.wav")
                out[did] = DialogueAudio(did, str(res.path), res.duration)
                self._report("voices", n, len(lines), scene=s.id, message=f"{spec.name} ({res.backend})")
        finally:
            self._voice_used = dict(engine.used)
            engine.close()
        self._report("lipsync", 0, len(out))
        for n, a in enumerate(out.values(), start=1):
            a.lipsync = lipsync_curves(Path(a.path))
            self._report("lipsync", n, len(out))
        return out

    def _scenes_and_render(self, timeline: dict, assets: dict[str, str], blender: BlenderManager,
                           renderer: RenderManager, ep: EpisodePaths) -> None:
        scenes = timeline["scenes"]
        total_frames = sum(s["frame_count"] for s in scenes)
        rendered_before = 0
        self._report("scenes", 0, len(scenes))
        self._report("render", 0, total_frames)
        for k, sd in enumerate(scenes, start=1):
            self._check_cancel()
            blend = ep.scene_blend(sd["id"])
            frames_dir = ep.scene_frames(sd["id"])
            job = {"scene": sd, "fps": FPS, "quality": self.settings.quality,
                   "character_assets": {c["id"]: assets[c["id"]] for c in sd["characters"]},
                   "frames_dir": str(frames_dir), "out_blend": str(blend), "use_gpu": self.settings.use_gpu,
                   "jpeg_quality": self.settings.preset.jpeg_quality,
                   "backdrop": self._backdrops.get(sd["location"])}
            self._report("scenes", k - 1, len(scenes), scene=sd["id"], message=f"Scene {sd['id']}: {sd['title']}")
            self._guard_frames(frames_dir, sd, assets)
            blender.run_script("run_build_scene.py", job, ep.temp / f"scene_{sd['id']:03d}_job.json",
                               ep.logs / f"blender_scene_{sd['id']:03d}.log")
            self._report("scenes", k, len(scenes), scene=sd["id"])

            base = rendered_before

            def on_frame(done: int, total: int, sid=sd["id"], base=base) -> None:
                self._report("render", base + done, total_frames, scene=sid,
                             message=f"Scene {sid}: frame {done}/{total}")

            if self.settings.render_engine == "ai":
                self._render_ai_scene(sd, blend, blender, ep, total_frames, base)
            else:
                had = len(list(frames_dir.glob("frame_*.jpg")))
                t0 = time.time()
                renderer.render_scene(blend, frames_dir, sd["frame_count"], ep.logs / f"render_{sd['id']:03d}.log",
                                      on_frame)
                if sd["frame_count"] - had > 20:  # measured speed feeds the next time estimate
                    self._render_seconds += time.time() - t0
                    self._render_frames += sd["frame_count"] - had
            rendered_before += sd["frame_count"]
            self._report("render", rendered_before, total_frames, scene=sd["id"])

    def _paint_backgrounds(self, timeline: dict) -> dict[str, str]:
        """Free CPU background painter (OpenVINO); skipped cleanly when not installed."""
        from engines.background_painter import BackgroundPainter

        locs = [s["location"] for s in timeline["scenes"]]
        if not self.settings.ai_backgrounds or not BackgroundPainter.available() or \
                not BackgroundPainter.is_installed():
            self._report("backgrounds", 1, 1, message="procedural 3D backgrounds")
            return {}
        self._report("backgrounds", 0, len(set(locs)))
        try:
            return BackgroundPainter().paint_all(
                locs, lambda k, n, loc: self._report("backgrounds", k, n, message=loc.replace("_", " ")))
        except Exception as exc:  # never lose an episode because of the optional painter
            log.warning("Background painting failed (%s); using procedural backgrounds", exc)
            return {}

    def _render_ai_scene(self, sd: dict, blend: Path, blender: BlenderManager, ep: EpisodePaths,
                         total_frames: int, base: int) -> Path:
        """AI video mode: Blender layout keyframe per shot -> ComfyUI (restyle, animate, lip-sync)."""
        from engines.ai_video.renderer import AISettings, AIVideoRenderer
        from engines.ai_video.shot_planner import plan_scene

        specs = {cid: s.data for cid, s in self.registry.characters.items()}
        shots = plan_scene(sd, specs)
        key_dir = ep.renders / f"scene_{sd['id']:03d}_keyframes"
        key_dir.mkdir(parents=True, exist_ok=True)
        frames = sorted({s.key_frame for s in shots})
        todo = [f for f in frames if not (key_dir / f"key_{f:05d}.png").exists()]
        if todo:
            blender.run_script("run_render_keyframes.py", {"frames": todo, "out_dir": str(key_dir),
                                                           "quality": "standard"},
                               ep.temp / f"keyframes_{sd['id']:03d}.json", ep.logs / f"keyframes_{sd['id']:03d}.log",
                               blend_file=blend)
        keyframes = {s.index: key_dir / f"key_{s.key_frame:05d}.png" for s in shots}
        ai = AIVideoRenderer(AISettings(server=self.settings.comfy_url, lipsync=self.settings.ai_lipsync),
                             ep.root / "ai_work", cancel_check=self.cancel_event.is_set)

        def on_shot(done: int, total: int) -> None:
            frac = done / max(1, total)
            self._report("render", base + int(frac * sd["frame_count"]), total_frames, scene=sd["id"],
                         message=f"Scene {sd['id']}: AI shot {done}/{total}")

        out = ai.render_scene(shots, keyframes, sd["frame_count"], ep.ai_clip(sd["id"]), on_shot)
        self._ai_reports[sd["id"]] = ai.report
        return out

    def _guard_frames(self, frames_dir: Path, sd: dict, assets: dict[str, str]) -> None:
        """Frames on disk are reused (resume after cancel) only if they belong to exactly
        this scene: same direction, quality and character assets. Otherwise they are cleared."""
        import hashlib
        import json

        sig_src = {"scene": sd, "quality": self.settings.quality,
                   "assets": {c["id"]: Path(assets[c["id"]]).stat().st_mtime for c in sd["characters"]}}
        if self._backdrops.get(sd.get("location")):  # only part of the signature when a painting is used
            sig_src["backdrop"] = self._backdrops[sd["location"]]
        sig = hashlib.sha256(json.dumps(sig_src, sort_keys=True, default=str).encode()).hexdigest()
        sig_file = frames_dir / ".scene_signature"
        frames_dir.mkdir(parents=True, exist_ok=True)
        old = sig_file.read_text().strip() if sig_file.exists() else None
        if old != sig:
            stale = list(frames_dir.glob("frame_*.jpg"))
            if stale:
                log.info("Scene %s changed: discarding %d old frames", sd["id"], len(stale))
                for f in stale:
                    f.unlink()
            sig_file.write_text(sig)

    def _assemble(self, timeline: dict, cues, ep: EpisodePaths) -> Path:
        asm = VideoAssembler(cancel_check=self.cancel_event.is_set)
        scenes = timeline["scenes"]
        clips = []
        clip_dir = ep.temp / "clips"
        clip_dir.mkdir(parents=True, exist_ok=True)
        steps = len(scenes) + 1
        for k, sd in enumerate(scenes, start=1):
            self._check_cancel()
            out = clip_dir / f"scene_{sd['id']:03d}.mp4"
            if self.settings.render_engine == "ai":
                out = ep.ai_clip(sd["id"])  # already 1280x720, 24 fps, exact frame count
            else:
                asm.encode_scene(ep.scene_frames(sd["id"]), sd["frame_count"], out)
            clips.append((out, sd["frame_count"] / FPS, sd.get("transition_in", "dissolve")))
            self._report("assemble", k, steps, scene=sd["id"])
        # transition_in of scene i+1 decides the join between i and i+1
        clips = [(c, d, (scenes[i]["transition_in"] if i > 0 else "dissolve")) for i, (c, d, _) in enumerate(clips)]
        asm.assemble(clips, cues, ep.master_audio, ep.final_video, timeline["total_seconds"])
        self._report("assemble", steps, steps)
        return ep.final_video
