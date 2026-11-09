"""Cinematic camera baking (run inside Blender).

The host-side shot planner (core/timeline_manager.py) decides *what* to film:
a list of shots with type, frame range, lens and camera/aim key positions.
Here one scene camera follows those shots: positions ease between keys inside
a shot (dolly, pan, orbit, tracking) and jump at shot boundaries (cuts).
Timeline markers record each shot's type for inspection in Blender.
"""
from __future__ import annotations

import bpy
from mathutils import Vector

from blender.animation_builder import write_curve
from blender.motion_math import ease_in_out


FSTOP = {"establishing": 11.0, "wide": 8.0, "dolly_out": 8.0, "orbit": 7.0, "tracking": 5.6, "medium": 2.8,
         "over_shoulder": 2.2, "closeup": 2.0, "extreme_closeup": 1.8, "low_angle": 3.2}


def _sample_shot(shot: dict, f: float) -> tuple[Vector, Vector, float]:
    keys = shot["keys"]
    if f <= keys[0]["frame"]:
        k = keys[0]
        return Vector(k["cam"]), Vector(k["aim"]), k.get("lens", shot["lens"])
    for a, b in zip(keys, keys[1:]):
        if a["frame"] <= f <= b["frame"]:
            u = (f - a["frame"]) / max(1e-6, b["frame"] - a["frame"])
            w = ease_in_out(u) if shot.get("ease", True) else u
            cam = Vector(a["cam"]).lerp(Vector(b["cam"]), w)
            aim = Vector(a["aim"]).lerp(Vector(b["aim"]), w)
            lens = a.get("lens", shot["lens"]) + (b.get("lens", shot["lens"]) - a.get("lens", shot["lens"])) * w
            return cam, aim, lens
    k = keys[-1]
    return Vector(k["cam"]), Vector(k["aim"]), k.get("lens", shot["lens"])


def build_camera(scene, shots: list[dict], n_frames: int, collection):
    cam_data = bpy.data.cameras.new("scene_camera")
    cam_data.clip_start = 0.05
    cam_data.clip_end = 400
    cam_data.sensor_width = 36
    cam_data.dof.use_dof = True  # shallow focus on the subject, like feature animation
    cam = bpy.data.objects.new("scene_camera", cam_data)
    collection.objects.link(cam)
    scene.camera = cam
    cam.rotation_mode = "QUATERNION"
    loc = [[], [], []]
    rot = [[], [], [], []]
    lens = []
    focus = []
    fstop = []
    shot_i = 0
    prev_q = None
    for f in range(n_frames):
        while shot_i + 1 < len(shots) and f >= shots[shot_i + 1]["start"]:
            shot_i += 1
            prev_q = None
        shot = shots[shot_i]
        c, a, ln = _sample_shot(shot, f)
        q = (a - c).to_track_quat("-Z", "Y")
        if prev_q is not None and prev_q.dot(q) < 0:  # keep quaternion hemisphere continuous
            q.negate()
        prev_q = q
        for i in range(3):
            loc[i].append(c[i])
        for i in range(4):
            rot[i].append(q[i])
        lens.append(ln)
        focus.append((a - c).length)
        fstop.append(FSTOP.get(shot["type"], 4.0))
    for i in range(3):
        write_curve(cam, "location", i, loc[i])
    for i in range(4):
        write_curve(cam, "rotation_quaternion", i, rot[i])
    write_curve(cam_data, "lens", -1, lens)
    write_curve(cam_data, "dof.focus_distance", -1, focus)
    write_curve(cam_data, "dof.aperture_fstop", -1, fstop, interpolation="CONSTANT")
    for shot in shots:
        m = scene.timeline_markers.new(f"{shot['type']}:{shot.get('subject') or 'all'}", frame=int(shot["start"]))
        m.camera = cam
    return cam
