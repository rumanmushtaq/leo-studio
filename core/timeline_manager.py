"""Scene timeline + staging + shot planning ("the director").

Input: enriched scenes, character registry and real dialogue audio durations.
Output per scene: a JSON-serialisable *direction* that Blender executes:
character root-motion paths, body/gesture clips, expressions, look-at,
lip-sync, props, effects, camera shots, sound cues and exact frame counts.

Timing rules: dialogue never overlaps or gets cut; scene length follows real
audio length plus action beats; if the episode is shorter than the minimum,
establishing shots and closing beats are extended (audio is never stretched
and no dialogue is duplicated).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from blender.motion_library import TALK_GESTURE
from blender.motion_math import sample_path, yaw_towards
from blender.rig_builder import compute_dims
from core.character_manager import CharacterRegistry
from core.scene_manager import ACTION_SECONDS
from core.script_parser import ParsedScene, ParsedScript
from utils.config import FPS, MIN_VIDEO_SECONDS, TRANSITION_SECONDS

LEAD_IN = TRANSITION_SECONDS + 0.2      # keep dialogue clear of the cross-fade
TAIL = 1.0
LINE_GAP = 0.3
ESTABLISH = 1.5
OFFSTAGE_X = 7.8
WALK_SPEED = 2.0
RUN_SPEED = 4.0

AMBIENCE = {
    "construction_site": "construction", "city_road": "traffic", "motorcycle_garage": "workshop",
    "car_workshop": "workshop", "police_station": "traffic", "park": "birds", "hideout": "hideout_hum",
    "school": "birds", "house": "birds", "shop": "crowd", "village": "birds",
}
LOCOMOTION = {"walk_in", "run_in", "fly_in", "ride_in", "walk_out", "run_away", "fly_out"}
BODY_ACTIONS = {"jump": "jump", "sit": "sit", "celebrate": "celebrate", "laugh": "laugh_body",
                "scared": "scared_body", "hero_landing": "hero_landing"}
GESTURE_ACTIONS = {"wave": "wave", "point": "point", "clap": "clap", "threaten": "threaten",
                   "look_around": "look_around", "work": "work", "power_up": "power_up",
                   "energy_shield": "power_up", "turn": "look_around"}


@dataclass
class DialogueAudio:
    """Real synthesized (or imported) audio for one line."""

    id: str
    path: str
    duration: float
    lipsync: dict = field(default_factory=dict)  # {"open": [...], "wide": [...], "round": [...]}


def F(seconds: float) -> int:
    return int(round(seconds * FPS))


class _Char:
    def __init__(self, cid: str, spec: dict, slot: tuple[float, float], facing: float):
        self.id = cid
        self.spec = spec
        self.dims = compute_dims(spec)
        self.slot = slot
        self.facing = facing
        self.path: list[dict] = []
        self.body: list[dict] = []
        self.gestures: list[dict] = []
        self.expressions: list[dict] = []
        self.look_at: list[dict] = []
        self.lipsync: list[dict] = []
        self.speech: list[tuple[int, int]] = []
        self.onstage_from: int | None = 0
        self.offstage_from: int | None = None

    def key(self, frame: int, x: float, y: float, yaw: float, z: float = 0.0, pitch: float = 0.0,
            ease: str = "linear") -> None:
        if self.path and frame <= self.path[-1]["frame"]:
            frame = self.path[-1]["frame"] + 1
        self.path.append({"frame": frame, "x": round(x, 4), "y": round(y, 4), "z": round(z, 4),
                          "yaw": round(yaw, 3), "pitch": round(pitch, 3), "ease": ease})

    def pos(self, frame: int) -> dict:
        return sample_path(self.path, frame)

    def busy_body(self, frame: int) -> bool:
        return any(b["start"] <= frame < b["end"] and b["clip"] in ("fly", "ride", "run", "walk", "hero_landing")
                   for b in self.body)


class TimelineManager:
    def __init__(self, registry: CharacterRegistry):
        self.registry = registry

    # ----------------------------------------------------------------- public
    def build(self, script: ParsedScript, audio: dict[str, DialogueAudio], min_seconds: float = MIN_VIDEO_SECONDS
              ) -> dict:
        """Build directions for all scenes, extending beats until ``min_seconds`` is reached."""
        extra = 0.0
        for _ in range(4):
            scenes = [self._direct_scene(s, audio, extra) for s in script.scenes]
            total = self.total_seconds(scenes)
            if total >= min_seconds:
                break
            extra += (min_seconds - total) / max(1, len(scenes)) + 0.05
        start = 0.0
        for i, sd in enumerate(scenes):
            sd["start_time"] = round(start, 4)
            start += sd["frame_count"] / FPS - (TRANSITION_SECONDS if i < len(scenes) - 1 else 0.0)
        return {"fps": FPS, "scenes": scenes, "total_seconds": round(self.total_seconds(scenes), 3),
                "extension_per_scene": round(extra, 3), "transition_seconds": TRANSITION_SECONDS}

    @staticmethod
    def total_seconds(scenes: list[dict]) -> float:
        frames = sum(s["frame_count"] for s in scenes)
        return frames / FPS - TRANSITION_SECONDS * max(0, len(scenes) - 1)

    # ---------------------------------------------------------------- staging
    def _stage(self, scene: ParsedScene) -> dict[str, _Char]:
        specs = {cid: self.registry.get_or_create(cid).data for cid in scene.characters}
        villains = [c for c in scene.characters if specs[c].get("role") == "villain"]
        others = [c for c in scene.characters if c not in villains]
        others.sort(key=lambda c: 0 if specs[c].get("role") == "hero" else 1)
        slots: dict[str, tuple[float, float]] = {}
        if not villains:
            n = len(others)
            order = sorted(others, key=lambda c: 0 if specs[c].get("role") == "hero" else 1)
            centred = sorted(range(n), key=lambda i: abs(i - (n - 1) / 2))
            for c, i in zip(order, centred):
                slots[c] = ((i - (n - 1) / 2) * 1.5, 0.25 * (i % 2))
        else:
            for k, c in enumerate(others):
                slots[c] = (-1.15 - 1.3 * k, 0.3 * (k % 2))
            for k, c in enumerate(villains):
                slots[c] = (1.15 + 1.25 * k, 0.3 * (k % 2))
        chars = {}
        for cid, (x, y) in slots.items():
            facing = yaw_towards(-x * 0.9, -4.0 - y)
            chars[cid] = _Char(cid, specs[cid], (x, y), facing)
        return chars

    # --------------------------------------------------------------- directing
    def _direct_scene(self, scene: ParsedScene, audio: dict[str, DialogueAudio], extra: float) -> dict:
        chars = self._stage(scene)
        events = scene.events
        # Exit actions wait until the character has finished speaking in this scene.
        last_line_idx = {}
        for i, e in enumerate(events):
            if e.kind == "dialogue" and e.speaker_id:
                last_line_idx[e.speaker_id] = i
        deferred_exits: list[dict] = []
        entering: dict[str, str] = {}
        for e in events:
            if e.kind == "visual":
                for a in e.actions:
                    if a["action"] in ("walk_in", "run_in", "fly_in", "ride_in") and a["character"] in chars:
                        entering.setdefault(a["character"], a["action"])
        for cid, ch in chars.items():
            if cid in entering:
                ch.onstage_from = None
                side = 1 if ch.spec.get("role") == "villain" else -1
                if entering[cid] == "fly_in":  # waits in the sky where the flight starts
                    sx = ch.slot[0] - 9.0 if ch.slot[0] <= 0 else ch.slot[0] + 9.0
                    ch.key(0, sx, ch.slot[1] + 3.0, yaw_towards(ch.slot[0] - sx, 0.0), z=7.5)
                    continue
                x0 = -13.0 if entering[cid] == "ride_in" else side * OFFSTAGE_X + ch.slot[0] * 0.2
                ch.key(0, x0, ch.slot[1], 90 * -side)
            else:
                ch.key(0, ch.slot[0], ch.slot[1], ch.facing)

        segments: list[dict] = []
        sfx: list[dict] = []
        effects: list[dict] = []
        props: list[dict] = []
        dialogues: list[dict] = []
        camera_hint: str | None = None
        t = LEAD_IN + ESTABLISH + extra * 0.7
        segments.append({"kind": "establish", "start": 0, "end": F(t)})
        sfx.append({"id": "transition", "time": 0.0, "gain": 0.5})

        for idx, e in enumerate(events):
            if e.kind == "visual" and e.actions:
                beat_start = F(t)
                beat_end = beat_start
                movers, gesturers = [], []
                cursor: dict[str, int] = {}  # one character's actions play in sequence
                for a in e.actions:
                    cid, act = a["character"], a["action"]
                    ch = chars.get(cid)
                    if ch is None:
                        continue
                    if act in ("walk_out", "run_away", "fly_out") and last_line_idx.get(cid, -1) > idx:
                        deferred_exits.append(a)
                        continue
                    if act == "hero_landing" and any(b["clip"] == "hero_landing" for b in ch.body):
                        continue  # already part of fly_in
                    at = cursor.get(cid, beat_start)
                    if act in ("walk_in", "run_in", "ride_in"):
                        at = max(beat_start, at - F(0.6))  # gestures may overlap the arrival turn
                    end = self._apply_action(ch, act, at, sfx, effects, props, chars)
                    cursor[cid] = end
                    beat_end = max(beat_end, end)
                    (movers if act in LOCOMOTION else gesturers).append((cid, act))
                if beat_end > beat_start:
                    segments.append({"kind": "action", "start": beat_start, "end": beat_end,
                                     "movers": movers, "gesturers": gesturers, "hint": camera_hint})
                    camera_hint = None
                    t = beat_end / FPS
            elif e.kind in ("dialogue", "narration"):
                did = self.dialogue_id(scene.id, idx)
                a = audio.get(did)
                if a is None:
                    raise ValueError(f"No audio for dialogue {did}: {e.text[:40]}")
                start = F(t + LINE_GAP)
                end = start + max(1, math.ceil(a.duration * FPS))
                speaker = e.speaker_id if e.kind == "dialogue" else "narrator"
                dialogues.append({"id": did, "speaker": speaker, "text": e.text, "emotion": e.emotion,
                                  "language": e.language, "start": start, "end": end, "audio": a.path,
                                  "duration": a.duration, "kind": e.kind})
                if speaker in chars:
                    self._speak(chars[speaker], chars, start, end, e.emotion or "neutral", a, idx)
                segments.append({"kind": "line", "start": start, "end": end, "speaker": speaker,
                                 "emotion": e.emotion, "hint": camera_hint, "dialogue": did})
                camera_hint = None
                t = end / FPS
            elif e.kind == "sfx":
                for act in e.actions:
                    sfx.append({"id": act["sfx"], "time": round(t, 3), "gain": 0.9})
            elif e.kind == "camera" and e.actions:
                camera_hint = e.actions[0]["camera"]
            elif e.kind == "music":
                sfx.append({"id": "music_cue", "time": round(t, 3), "gain": 0.0, "text": e.text})

        for a in deferred_exits:
            start = F(t + 0.2)
            end = self._apply_action(chars[a["character"]], a["action"], start, sfx, effects, props, chars)
            segments.append({"kind": "action", "start": start, "end": end, "movers": [(a["character"], a["action"])],
                             "gesturers": [], "hint": None})
            t = end / FPS

        for fx in effects:  # shields stay up across the next lines of dialogue
            lines = fx.pop("extend_lines", 0)
            if lines:
                later = [d["end"] for d in dialogues if d["start"] > fx["start"]]
                fx["end"] = later[min(len(later), lines) - 1] if later else fx["start"] + F(4)
                fx["end"] = max(fx["end"], fx["start"] + F(3))

        t += TAIL + extra * 0.3 + LEAD_IN
        n_frames = F(t)
        segments.append({"kind": "tail", "start": F(t - TAIL - extra * 0.3 - LEAD_IN), "end": n_frames})
        self._finish_tracks(chars, n_frames)
        shots = self._plan_shots(segments, chars, n_frames, scene.location)
        return {
            "id": scene.id, "title": scene.title, "location": scene.location, "env_seed": scene.id * 7 + 3,
            "frame_count": n_frames, "duration": round(n_frames / FPS, 4),
            "transition_in": scene.transition_in,
            "characters": [self._char_out(c) for c in chars.values()],
            "dialogues": dialogues, "effects": effects, "props": props, "camera_shots": shots,
            "sfx": sorted(sfx, key=lambda s: s["time"]), "ambience": AMBIENCE.get(scene.location, "birds"),
            "segments": segments,
        }

    @staticmethod
    def dialogue_id(scene_id: int, event_index: int) -> str:
        return f"s{scene_id:02d}_e{event_index:03d}"

    def _apply_action(self, ch: _Char, act: str, f0: int, sfx: list, effects: list, props: list,
                      chars: dict[str, _Char]) -> int:
        """Schedule one action; returns the frame where it ends."""
        H = ch.dims["H"]
        here = ch.pos(f0)
        if act in ("walk_in", "run_in"):
            speed = RUN_SPEED if act == "run_in" else WALK_SPEED * (0.9 if H < 1.45 else 1.0)
            ch.key(f0, here["x"], here["y"], here["yaw"])
            dist = math.dist((here["x"], here["y"]), ch.slot)
            f1 = f0 + max(F(1.0), F(dist / speed))
            ch.key(f1, ch.slot[0], ch.slot[1], here["yaw"])
            ch.key(f1 + F(0.45), ch.slot[0], ch.slot[1], ch.facing, ease="smooth")
            ch.body.append({"clip": "run" if act == "run_in" else "walk", "start": f0, "end": f1 + F(0.15),
                            "params": {"speed": dist / max(1e-3, (f1 - f0) / FPS)}})
            ch.onstage_from = f0 + F(1.0)
            self._footsteps(sfx, f0, f1, 0.5 if act == "walk_in" else 0.31, H)
            return f1 + F(0.45)
        if act == "fly_in":
            sx = ch.slot[0] - 9.0 if ch.slot[0] <= 0 else ch.slot[0] + 9.0
            yaw_dir = yaw_towards(ch.slot[0] - sx, 0.0)
            ch.key(f0, sx, ch.slot[1] + 3.0, yaw_dir, z=7.5)
            f1 = f0 + F(2.6)
            ch.key(f1, ch.slot[0], ch.slot[1], yaw_dir, z=0.0, ease="arc")
            ch.key(f1 + F(0.5), ch.slot[0], ch.slot[1], ch.facing, ease="smooth")
            ch.body.append({"clip": "fly", "start": f0, "end": f1 + 2, "blend": False, "params": {"pitch": 70}})
            ch.body.append({"clip": "hero_landing", "start": f1 - 2, "end": f1 + F(1.5)})
            effects.append({"type": "landing_impact", "start": f1, "end": f1 + F(0.7), "x": ch.slot[0],
                            "y": ch.slot[1], "character": ch.id})
            sfx += [{"id": "flying", "time": round(f0 / FPS, 3), "gain": 0.9},
                    {"id": "landing", "time": round(f1 / FPS, 3), "gain": 1.0},
                    {"id": "hero_entrance", "time": round(f1 / FPS + 0.1, 3), "gain": 0.8}]
            ch.onstage_from = f0 + F(1.2)
            return f1 + F(1.5)
        if act == "ride_in":
            ch.key(f0, -13.0, ch.slot[1], -90.0)
            f1 = f0 + F(3.4)
            ch.key(f1, ch.slot[0], ch.slot[1], -90.0, ease="smooth")
            ch.key(f1 + F(0.6), ch.slot[0], ch.slot[1], -60.0, ease="smooth")
            ch.body.append({"clip": "ride", "start": 0, "end": 10 ** 6, "blend": False,
                            "params": {"seat_z": 0.74}})
            props.append({"type": "motorcycle", "character": ch.id, "start": f0, "end": f1 + F(0.6),
                          "color": [0.1, 0.35, 0.85]})
            sfx.append({"id": "motorcycle", "time": round(f0 / FPS, 3), "gain": 0.9, "duration": 4.5})
            ch.onstage_from = f0 + F(1.5)
            return f1 + F(0.6)
        if act in ("walk_out", "run_away", "fly_out"):
            side = 1 if ch.spec.get("role") == "villain" else -1
            tx = side * (OFFSTAGE_X + 3.5)
            ch.key(f0, here["x"], here["y"], here["yaw"])
            turn = F(0.3)
            yaw = yaw_towards(tx - here["x"], 0.0)
            ch.key(f0 + turn, here["x"], here["y"], yaw, ease="smooth")
            if act == "fly_out":
                f1 = f0 + turn + F(2.2)
                ch.key(f1, tx, here["y"] + 3, yaw, z=8.0, ease="smooth")
                ch.body.append({"clip": "jump", "start": f0, "end": f0 + F(0.6)})
                ch.body.append({"clip": "fly", "start": f0 + F(0.4), "end": f1 + 1, "params": {"pitch": 60}})
                sfx.append({"id": "flying", "time": round(f0 / FPS, 3), "gain": 0.9})
            else:
                speed = RUN_SPEED if act == "run_away" else WALK_SPEED
                dist = abs(tx - here["x"])
                f1 = f0 + turn + F(dist / speed)
                ch.key(f1, tx, here["y"], yaw)
                ch.body.append({"clip": "run" if act == "run_away" else "walk", "start": f0 + turn - 2,
                                "end": f1 + 1, "params": {"speed": speed}})
                self._footsteps(sfx, f0 + turn, f1, 0.31 if act == "run_away" else 0.5, H)
            ch.offstage_from = f0 + turn + F(1.6)
            return f0 + turn + F(1.8)
        if act in BODY_ACTIONS:
            dur = F(ACTION_SECONDS.get(act, 1.5))
            ch.body.append({"clip": BODY_ACTIONS[act], "start": f0, "end": f0 + dur})
            if act == "celebrate":
                sfx.append({"id": "crowd", "time": round(f0 / FPS, 3), "gain": 0.6})
                ch.expressions.append({"emotion": "happy", "start": f0, "end": f0 + dur + F(1)})
            elif act == "laugh":
                ch.expressions.append({"emotion": "laughing", "start": f0, "end": f0 + dur})
            elif act == "scared":
                ch.expressions.append({"emotion": "scared", "start": f0, "end": f0 + dur})
            return f0 + dur
        if act in GESTURE_ACTIONS:
            dur = F(ACTION_SECONDS.get(act, 1.5))
            g = {"clip": GESTURE_ACTIONS[act], "start": f0, "end": f0 + dur}
            if act == "work":
                g["persistent"] = True
            ch.gestures.append(g)
            if act == "energy_shield":
                effects.append({"type": "energy_shield", "character": ch.id, "start": f0 + F(0.4),
                                "end": f0 + F(0.4), "extend_lines": 2})
                sfx.append({"id": "shield", "time": round(f0 / FPS + 0.4, 3), "gain": 0.9})
                ch.expressions.append({"emotion": "confident", "start": f0, "end": f0 + dur})
            elif act == "power_up":
                effects.append({"type": "power_up", "character": ch.id, "start": f0, "end": f0 + dur})
                sfx.append({"id": "magic", "time": round(f0 / FPS, 3), "gain": 0.9})
            elif act == "threaten":
                ch.expressions.append({"emotion": "angry", "start": f0, "end": f0 + dur})
            return f0 + dur
        return f0

    def _footsteps(self, sfx: list, f0: int, f1: int, interval: float, H: float) -> None:
        t = f0 / FPS + 0.2
        while t < f1 / FPS:
            sfx.append({"id": "footsteps", "time": round(t, 3), "gain": 0.35 if H > 1.45 else 0.28})
            t += interval

    def _speak(self, ch: _Char, chars: dict[str, _Char], start: int, end: int, emotion: str, a: DialogueAudio,
               idx: int) -> None:
        ch.speech.append((start, end))
        if a.lipsync:
            ch.lipsync.append({"start": start, **a.lipsync})
        ch.expressions.append({"emotion": emotion, "start": start - F(0.2), "end": end + F(0.5)})
        if not ch.busy_body(start):
            clip = TALK_GESTURE.get(emotion, "talk")
            if emotion == "laughing":
                ch.body.append({"clip": "laugh_body", "start": start, "end": min(end, start + F(1.8))})
                clip = "talk_open"
            ch.gestures.append({"clip": clip, "start": start - F(0.1), "end": end + F(0.2),
                                "params": {"seed": idx * 0.7}})
        role = ch.spec.get("role")
        for other in chars.values():
            if other is ch:
                continue
            other.look_at.append({"start": start, "end": end + F(0.3), "target": ch.id})
            orole = other.spec.get("role")
            react = None
            if emotion == "angry" and role == "villain":
                react = "confident" if orole == "hero" else "scared" if orole != "villain" else "laughing"
            elif emotion == "angry" and orole == "villain":
                react = "surprised"
            elif emotion in ("happy", "laughing") and role != "villain":
                react = "happy" if orole != "villain" else "angry"
            elif emotion == "confident" and orole == "villain":
                react = "surprised"
            if react:
                other.expressions.append({"emotion": react, "start": start + F(0.4), "end": end + F(0.6)})

    def _finish_tracks(self, chars: dict[str, _Char], n: int) -> None:
        for ch in chars.values():
            for b in ch.body:
                b["end"] = min(b["end"], n)
            for g in ch.gestures:
                if g.pop("persistent", False):
                    nxt = [s for s, _ in ch.speech if s > g["start"]]
                    g["end"] = min(nxt[0] - F(0.1) if nxt else g["start"] + F(8), g["start"] + F(8), n)
            last = ch.path[-1]
            if last["frame"] < n:
                ch.key(n, last["x"], last["y"], last["yaw"], last["z"], last["pitch"])

    def _char_out(self, ch: _Char) -> dict:
        return {"id": ch.id, "role": ch.spec.get("role", "neutral"), "height": ch.dims["H"],
                "head_c": ch.dims["head_c"], "slot": list(ch.slot), "facing": ch.facing,
                "default_emotion": ch.spec.get("default_emotion", "neutral"),
                "path": ch.path, "body": ch.body, "gestures": ch.gestures, "expressions": ch.expressions,
                "look_at": ch.look_at, "lipsync": ch.lipsync, "speech": ch.speech,
                "onstage_from": ch.onstage_from, "offstage_from": ch.offstage_from}

    # ----------------------------------------------------------------- camera
    def _plan_shots(self, segments: list[dict], chars: dict[str, _Char], n: int, location: str) -> list[dict]:
        shots: list[dict] = []
        lead = F(0.2)
        last_speaker = None
        speaker_count: dict[str, int] = {}
        for i, seg in enumerate(segments):
            start = 0 if i == 0 else max(0, seg["start"] - lead)
            end = n if i == len(segments) - 1 else max(start + 1, segments[i + 1]["start"] - lead)
            kind = seg["kind"]
            onstage = self._onstage(chars, (start + end) // 2)
            if kind in ("establish", "tail"):
                shots += [self._wide(start, end, chars, onstage, establishing=(kind == "establish"),
                                     dolly_out=(kind == "tail"))]
            elif kind == "action":
                shots += self._action_shots(seg, start, end, chars, onstage)
            else:
                sp = seg["speaker"]
                hint = seg.get("hint")
                if sp not in chars or sp not in self._onstage(chars, seg["start"] + 2):
                    shots.append(self._wide(start, end, chars, onstage, orbit=(sp == "narrator")))
                else:
                    count = speaker_count.get(sp, 0)
                    speaker_count[sp] = count + 1
                    long_line = (seg["end"] - seg["start"]) > F(4.5)
                    if hint in ("wide", "orbit", "pan"):
                        shots.append(self._wide(start, end, chars, onstage, orbit=hint == "orbit"))
                    elif hint in ("closeup", "extreme_closeup"):
                        shots.append(self._close(sp, start, end, chars, extreme=hint == "extreme_closeup"))
                    elif hint == "over_shoulder" and last_speaker in onstage and last_speaker != sp:
                        shots.append(self._ots(last_speaker, sp, start, end, chars))
                    elif seg.get("emotion") in ("surprised", "scared", "angry") and count > 0:
                        shots.append(self._close(sp, start, end, chars))
                    elif (last_speaker and last_speaker != sp and last_speaker in onstage and count > 0
                          and len(shots) % 2 == 0):
                        shots.append(self._ots(last_speaker, sp, start, end, chars))
                    else:
                        shots.append(self._medium(sp, start, end, chars, dolly=long_line or count == 0))
                last_speaker = sp
        # merge very short shots into their predecessor
        merged: list[dict] = []
        for s in shots:
            if merged and s["end"] - s["start"] < F(0.9):
                merged[-1]["end"] = s["end"]
                merged[-1]["keys"][-1]["frame"] = max(merged[-1]["keys"][-1]["frame"], s["end"])
                continue
            merged.append(s)
        for a, b in zip(merged, merged[1:]):
            b["start"] = a["end"]
        return merged

    def _onstage(self, chars: dict[str, _Char], f: int) -> list[str]:
        out = []
        for cid, ch in chars.items():
            p = ch.pos(f)
            if abs(p["x"]) < 7.2 and p["z"] < 4:
                out.append(cid)
        return out

    def _head(self, ch: _Char, f: int) -> tuple[float, float, float]:
        p = ch.pos(f)
        return (p["x"], p["y"], p["z"] + ch.dims["head_c"])

    @staticmethod
    def _shot(kind: str, subject, start: int, end: int, lens: float, keys: list[dict], ease: bool = True) -> dict:
        return {"type": kind, "subject": subject, "start": start, "end": end, "lens": lens, "keys": keys,
                "ease": ease}

    def _wide(self, start: int, end: int, chars, onstage, establishing=False, dolly_out=False, orbit=False):
        xs = [chars[c].pos((start + end) // 2)["x"] for c in onstage] or [0.0]
        cx = max(-3.0, min(3.0, (min(xs) + max(xs)) / 2))
        spread = (max(xs) - min(xs)) if xs else 0
        dist = max(8.5, 6.0 + spread * 0.9)
        if establishing:
            k0 = {"frame": start, "cam": [cx - 2.5, -dist - 3.0, 4.2], "aim": [cx, 2.0, 1.6], "lens": 24}
            k1 = {"frame": end, "cam": [cx, -dist, 2.3], "aim": [cx, 0.5, 1.1], "lens": 28}
            return self._shot("establishing", None, start, end, 26, [k0, k1])
        if orbit:
            keys = []
            for j, ang in enumerate((-18, 0, 18)):
                a = math.radians(ang)
                f = start + (end - start) * j // 2
                keys.append({"frame": f, "cam": [cx + math.sin(a) * dist, -math.cos(a) * dist, 2.4],
                             "aim": [cx, 0.4, 1.1], "lens": 30})
            return self._shot("orbit", None, start, end, 30, keys)
        d1 = dist + (1.5 if dolly_out else -0.8)
        k0 = {"frame": start, "cam": [cx, -dist, 2.3], "aim": [cx, 0.5, 1.1], "lens": 30}
        k1 = {"frame": end, "cam": [cx, -d1, 2.4 if dolly_out else 2.2], "aim": [cx, 0.5, 1.1], "lens": 30}
        return self._shot("dolly_out" if dolly_out else "wide", None, start, end, 30, [k0, k1])

    def _front_dir(self, ch: _Char, f: int) -> tuple[float, float]:
        """Unit vector from the subject toward a 3/4 front camera position."""
        yaw = math.radians(ch.pos(f)["yaw"])
        fx, fy = math.sin(yaw), -math.cos(yaw)  # facing direction
        dx, dy = 0.45 * fx, 0.55 * fy - 0.55
        n = math.hypot(dx, dy) or 1
        return dx / n, dy / n

    def _medium(self, cid: str, start: int, end: int, chars, dolly: bool = False):
        ch = chars[cid]
        hx, hy, hz = self._head(ch, start)
        H = ch.dims["H"]
        aim = [hx, hy, hz - 0.24 * H]
        dx, dy = self._front_dir(ch, start)
        d0 = 2.3 * H + 0.8
        d1 = d0 - (0.5 if dolly else 0.15)
        k0 = {"frame": start, "cam": [hx + dx * d0, hy + dy * d0, hz - 0.05], "aim": aim, "lens": 40}
        k1 = {"frame": end, "cam": [hx + dx * d1, hy + dy * d1, hz - 0.08], "aim": aim, "lens": 40}
        return self._shot("medium", cid, start, end, 40, [k0, k1])

    def _close(self, cid: str, start: int, end: int, chars, extreme: bool = False):
        ch = chars[cid]
        hx, hy, hz = self._head(ch, start)
        dx, dy = self._front_dir(ch, start)
        d0 = (1.2 if extreme else 2.1) * (ch.dims["head_r"] / 0.2)
        aim = [hx, hy, hz - 0.06]
        k0 = {"frame": start, "cam": [hx + dx * d0, hy + dy * d0, hz + 0.02], "aim": aim, "lens": 50}
        k1 = {"frame": end, "cam": [hx + dx * d0 * 0.92, hy + dy * d0 * 0.92, hz + 0.02], "aim": aim, "lens": 50}
        return self._shot("extreme_closeup" if extreme else "closeup", cid, start, end, 50, [k0, k1])

    def _ots(self, listener: str, speaker: str, start: int, end: int, chars):
        L, S = chars[listener], chars[speaker]
        lx, ly, lz = self._head(L, start)
        sx, sy, sz = self._head(S, start)
        vx, vy = lx - sx, ly - sy
        n = math.hypot(vx, vy) or 1
        cam = [lx + vx / n * 0.9, min(ly, sy) - 1.3, lz + 0.12]
        aim = [sx, sy, sz - 0.12]
        k0 = {"frame": start, "cam": cam, "aim": aim, "lens": 35}
        k1 = {"frame": end, "cam": [cam[0], cam[1] + 0.15, cam[2]], "aim": aim, "lens": 35}
        return self._shot("over_shoulder", speaker, start, end, 35, [k0, k1])

    def _action_shots(self, seg: dict, start: int, end: int, chars, onstage) -> list[dict]:
        movers = seg.get("movers", [])
        hint = seg.get("hint")
        fliers = [c for c, a in movers if a == "fly_in"]
        riders = [c for c, a in movers if a == "ride_in"]
        if fliers:
            ch = chars[fliers[0]]
            land = next(b["start"] for b in ch.body if b["clip"] == "hero_landing") + 2
            keys = []
            f = start
            while f < land:
                p = ch.pos(f)
                keys.append({"frame": f, "cam": [p["x"] * 0.5 + 1.0, -9.0, 1.4 + p["z"] * 0.35],
                             "aim": [p["x"], p["y"], p["z"] + 0.7], "lens": 28})
                f += 6
            keys.append({"frame": land, "cam": [ch.slot[0] * 0.5 + 1.0, -9.0, 1.4], "aim": [ch.slot[0], ch.slot[1], 0.8],
                         "lens": 28})
            track = self._shot("tracking", ch.id, start, land, 28, keys, ease=False)
            H = ch.dims["H"]
            sx, sy = ch.slot
            low = self._shot("low_angle", ch.id, land, end, 26, [
                {"frame": land, "cam": [sx + 1.3, sy - 2.6, 0.35], "aim": [sx, sy, 0.75 * H], "lens": 26},
                {"frame": end, "cam": [sx + 0.9, sy - 2.3, 0.45], "aim": [sx, sy, 0.85 * H], "lens": 26}])
            return [track, low]
        if riders:
            ch = chars[riders[0]]
            keys = []
            for f in range(start, end + 1, 8):
                p = ch.pos(f)
                keys.append({"frame": f, "cam": [p["x"] + 1.5, p["y"] - 6.0, 1.6], "aim": [p["x"], p["y"], 0.9],
                             "lens": 32})
            return [self._shot("tracking", ch.id, start, end, 32, keys, ease=False)]
        gest = seg.get("gesturers", [])
        if hint in ("closeup", "medium") and gest:
            fn = self._close if hint == "closeup" else self._medium
            return [fn(gest[0][0], start, end, chars)]
        if gest and not movers and any(a in ("power_up", "energy_shield", "point", "wave") for _, a in gest):
            return [self._medium(gest[0][0], start, end, chars, dolly=True)]
        return [self._wide(start, end, chars, onstage or [c for c, _ in movers], orbit=hint == "orbit")]
