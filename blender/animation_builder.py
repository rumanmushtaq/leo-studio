"""Bake scene timelines into Blender keyframes (run inside Blender).

Per frame, each character's pose is evaluated in layers:
  1. body layer   - idle base + scheduled body clips (walk, fly, landing...)
                    cross-faded with smoothstep weights (motion blending)
  2. gesture layer - upper-body clips (talk, point, wave...) masked to the
                    bones they animate
  3. head look-at - head yaw toward the active speaker
  4. face layer   - expression presets, blinking and lip-sync visemes
The result is written as per-frame keyframes (linear interpolation) into one
Action per character plus shape-key and root-motion curves.
"""
from __future__ import annotations

import json
import math
import random

import bpy
from mathutils import Quaternion, Vector

from blender import motion_library as ml
from blender.motion_math import (IDENTITY, Z, clamp, qmul, axis_angle, sample_path, smoothstep,
                                 yaw_towards)

BLEND_SEC = 0.3
GESTURE_BLEND_SEC = 0.25
EXPR_BLEND_SEC = 0.3


def _fcurves_for(id_owner, action):
    """F-Curve collection of an action, for both slotted (4.4+) and legacy actions."""
    try:
        from bpy_extras.anim_utils import action_get_channelbag_for_slot

        ad = id_owner.animation_data
        bag = action_get_channelbag_for_slot(action, ad.action_slot)
        if bag is not None:
            return bag.fcurves
    except ImportError:
        pass
    return action.fcurves


def write_curve(id_owner, data_path: str, index: int, values: list[float], start_frame: int = 0,
                interpolation: str = "LINEAR") -> None:
    """Write one value per frame as keyframes on ``id_owner`` (object or shape-key block)."""
    if not values:
        return
    if index >= 0:
        id_owner.keyframe_insert(data_path, index=index, frame=start_frame)
    else:
        id_owner.keyframe_insert(data_path, frame=start_frame)
    action = id_owner.animation_data.action
    fcurves = _fcurves_for(id_owner, action)
    fc = fcurves.find(data_path, index=max(index, 0))
    n = len(values)
    kp = fc.keyframe_points
    if len(kp) < n:
        kp.add(n - len(kp))
    co = []
    for i, v in enumerate(values):
        co += [start_frame + i, v]
    kp.foreach_set("co", co)
    interp = {"CONSTANT": 0, "LINEAR": 1, "BEZIER": 2}[interpolation]
    kp.foreach_set("interpolation", [interp] * n)
    for k in kp:
        k.handle_left_type = k.handle_right_type = "AUTO_CLAMPED"
    fc.update()


def write_sparse(id_owner, data_path: str, keys: list[tuple[int, float]], index: int = -1,
                 interpolation: str = "CONSTANT") -> None:
    """Few explicit keys (visibility toggles etc.)."""
    for frame, value in keys:
        if index >= 0:
            getattr(id_owner, data_path.split(".")[-1])
            vec = getattr(id_owner, data_path)
            vec[index] = value
            id_owner.keyframe_insert(data_path, index=index, frame=frame)
        else:
            setattr(id_owner, data_path, value)
            id_owner.keyframe_insert(data_path, frame=frame)
    action = id_owner.animation_data.action
    fc = _fcurves_for(id_owner, action).find(data_path, index=max(index, 0))
    for k in fc.keyframe_points:
        k.interpolation = interpolation


def _clip_weight(f: float, start: float, end: float, blend_frames: float) -> float:
    if f < start or f >= end:
        return 0.0
    return smoothstep((f - start) / blend_frames) * smoothstep((end - f) / blend_frames)


def _wrap180(a: float) -> float:
    return (a + 180.0) % 360.0 - 180.0


class CharacterBaker:
    def __init__(self, rig, face, direction: dict, scene_dir: dict, fps: int):
        self.rig = rig
        self.face = face
        self.dir = direction
        self.scene_dir = scene_dir
        self.fps = fps
        self.dims = json.loads(rig["dims"])
        self.rest = {b.name: b.matrix_local.to_quaternion() for b in rig.data.bones}
        self.rest_inv = {k: q.inverted() for k, q in self.rest.items()}
        self.params = {"H": self.dims["H"], "hip_height": self.dims["hip_z"], "belly": self.dims.get("belly", 0.0),
                       "seed": (sum(map(ord, direction["id"])) % 17) / 3.0}
        self.paths = {c["id"]: c["path"] for c in scene_dir["characters"]}

    # ------------------------------------------------------------ evaluation
    def body_pose(self, f: float) -> dict:
        t = f / self.fps
        pose = ml.idle(t, 9999, self.params)
        bf = BLEND_SEC * self.fps
        for clip in self.dir.get("body", []):
            w = _clip_weight(f, clip["start"], clip["end"], bf if clip.get("blend", True) else 0.5)
            if w <= 0:
                continue
            fn = ml.BODY_CLIPS.get(clip["clip"])
            if fn is None:
                continue
            p = {**self.params, **clip.get("params", {})}
            local_t = (f - clip["start"]) / self.fps
            dur = (clip["end"] - clip["start"]) / self.fps
            pose = ml.blend_poses(pose, fn(local_t, dur, p), w)
        gb = GESTURE_BLEND_SEC * self.fps
        for g in self.dir.get("gestures", []):
            w = _clip_weight(f, g["start"], g["end"], gb)
            if w <= 0:
                continue
            fn = ml.GESTURE_CLIPS.get(g["clip"])
            if fn is None:
                continue
            p = {**self.params, **g.get("params", {})}
            gp = fn((f - g["start"]) / self.fps, (g["end"] - g["start"]) / self.fps, p)
            mask = list(gp["rot"].keys()) + list(gp["loc"].keys())
            pose = ml.blend_poses(pose, gp, w, mask=mask)
        return pose

    def look_yaw(self, f: float, body_yaw: float) -> float:
        lb = 0.35 * self.fps
        yaw = 0.0
        me = sample_path(self.dir["path"], f)
        for look in self.dir.get("look_at", []):
            w = _clip_weight(f, look["start"], look["end"], lb)
            if w <= 0 or look["target"] not in self.paths:
                continue
            tgt = sample_path(self.paths[look["target"]], f)
            want = yaw_towards(tgt["x"] - me["x"], tgt["y"] - me["y"])
            yaw += w * clamp(_wrap180(want - body_yaw), -55, 55)
        return yaw

    def face_values(self, f: float) -> dict:
        t = f / self.fps
        eb = EXPR_BLEND_SEC * self.fps
        base = dict(ml.EXPRESSIONS[self.dir.get("default_emotion", "neutral")
                                   if self.dir.get("default_emotion") in ml.EXPRESSIONS else "neutral"])
        for e in self.dir.get("expressions", []):
            w = _clip_weight(f, e["start"], e["end"], eb)
            if w <= 0:
                continue
            preset = ml.EXPRESSIONS.get(e["emotion"], ml.EXPRESSIONS["neutral"])
            base = {k: base[k] + (preset[k] - base[k]) * w for k in base}
        vals = {"Blink": base["Squint"] * 0.45, "Open": base["Open"], "Wide": 0.0, "Round": base["Round"],
                "Smile": base["Smile"], "Frown": base["Frown"], "MBP": 0.0, "FV": 0.0, "brow_up": base["brow_up"],
                "brow_tilt": base["brow_tilt"]}
        if any(e["emotion"] == "laughing" and e["start"] <= f < e["end"] for e in self.dir.get("expressions", [])):
            vals["Open"] = max(vals["Open"], 0.2 + 0.3 * abs(math.sin(2 * math.pi * 4 * t)))
        for ls in self.dir.get("lipsync", []):
            i = int(f - ls["start"])
            if 0 <= i < len(ls["open"]):
                o = ls["open"][i]
                vals["Open"] = max(vals["Open"] * 0.3, o)
                vals["Wide"] = ls["wide"][i]
                vals["Round"] = max(vals["Round"] * 0.3, ls["round"][i])
                if "mbp" in ls:  # letter-level lip-sync: pressed lips / lip-to-teeth shapes
                    vals["MBP"] = ls["mbp"][i]
                    vals["FV"] = ls["fv"][i]
                    vals["Open"] *= 1 - 0.8 * vals["MBP"]
                vals["Smile"] *= (1 - 0.6 * o)
        vals["Blink"] = max(vals["Blink"], self.blinks.get(int(f), 0.0))
        return vals

    def _blink_track(self, n: int) -> dict:
        rng = random.Random(self.dir["id"])
        out: dict[int, float] = {}
        f = rng.uniform(0.5, 2.0) * self.fps
        while f < n:
            for k, v in enumerate((0.5, 1.0, 1.0, 0.5)):
                out[int(f) + k] = v
            f += rng.uniform(2.2, 4.8) * self.fps
        return out

    # ------------------------------------------------------------------ bake
    def bake(self, n_frames: int) -> None:
        rig = self.rig
        self.blinks = self._blink_track(n_frames)
        rig.animation_data_create()
        rig.animation_data.action = bpy.data.actions.new(f"{self.dir['id']}_scene_action")
        rot_ch: dict[str, list[list[float]]] = {}
        loc_ch: dict[str, list[list[float]]] = {}
        obj_loc = [[], [], []]
        obj_rot = [[], [], []]
        face_ch = {k: [] for k in ("Blink", "Open", "Wide", "Round", "Smile", "Frown", "MBP", "FV")}
        anim_bones = [b for b in ml.BODY_BONES if b in rig.pose.bones] + ["jaw", "brow_L", "brow_R"]
        for b in anim_bones:
            rot_ch[b] = [[], [], [], []]
            loc_ch[b] = [[], [], []]
        r_head = self.dims["head_r"]
        for f in range(n_frames):
            pose = self.body_pose(f)
            pth = sample_path(self.dir["path"], f)
            yaw = pth["yaw"]
            fv = self.face_values(f)
            # head look-at on top of the body pose
            ly = self.look_yaw(f, yaw)
            if abs(ly) > 0.01:
                pose["rot"]["head"] = qmul(axis_angle(Z, ly * 0.7), pose["rot"].get("head", IDENTITY))
                pose["rot"]["neck"] = qmul(axis_angle(Z, ly * 0.3), pose["rot"].get("neck", IDENTITY))
            pose["rot"]["jaw"] = axis_angle((1, 0, 0), 12 * fv["Open"])
            for side, sgn in (("L", -1), ("R", 1)):
                pose["rot"][f"brow_{side}"] = axis_angle((0, 1, 0), sgn * fv["brow_tilt"])
                pose["loc"][f"brow_{side}"] = (0.0, 0.0, 0.07 * r_head * fv["brow_up"])
            for b in anim_bones:
                qa = Quaternion(pose["rot"].get(b, IDENTITY))
                ql = self.rest_inv[b] @ qa @ self.rest[b]
                for i in range(4):
                    rot_ch[b][i].append(ql[i])
                la = Vector(pose["loc"].get(b, (0.0, 0.0, 0.0)))
                ll = self.rest_inv[b] @ la
                for i in range(3):
                    loc_ch[b][i].append(ll[i])
            obj_loc[0].append(pth["x"])
            obj_loc[1].append(pth["y"])
            obj_loc[2].append(pth["z"] + pose.get("root_z", 0.0))
            obj_rot[0].append(math.radians(pth["pitch"] + pose.get("root_pitch", 0.0)))
            obj_rot[1].append(0.0)
            obj_rot[2].append(math.radians(yaw))
            for k in face_ch:
                face_ch[k].append(clamp(fv[k], 0.0, 1.0))

        for b in anim_bones:
            pb = rig.pose.bones[b]
            pb.rotation_mode = "QUATERNION"
            for i in range(4):
                write_curve(rig, f'pose.bones["{b}"].rotation_quaternion', i, rot_ch[b][i])
            if any(abs(v) > 1e-6 for ch in loc_ch[b] for v in ch):
                for i in range(3):
                    write_curve(rig, f'pose.bones["{b}"].location', i, loc_ch[b][i])
        rig.rotation_mode = "XYZ"
        for i in range(3):
            write_curve(rig, "location", i, obj_loc[i])
            write_curve(rig, "rotation_euler", i, obj_rot[i])
        if self.face is not None and self.face.data.shape_keys:
            sk = self.face.data.shape_keys
            sk.animation_data_create()
            sk.animation_data.action = bpy.data.actions.new(f"{self.dir['id']}_face_action")
            for k, vals in face_ch.items():
                if k in sk.key_blocks:
                    write_curve(sk, f'key_blocks["{k}"].value', -1, vals)
