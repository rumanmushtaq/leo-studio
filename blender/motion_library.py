"""Reusable procedural motion clips for the shared humanoid rig.

Every clip is a pure function ``clip(t, dur, p) -> Pose`` where ``t`` is the
time in seconds since the clip started and ``p`` holds rig dimensions (``H`` =
character height) and clip parameters (e.g. walking speed). Rotations are
expressed around *armature-space* axes and converted to each bone's local
space at bake time, so one clip drives every character regardless of size.

Convention: characters face -Y, +X is the character's left, +Z is up.
For bones pointing down (arms, legs): rotation about -X swings them forward.
For bones pointing up (spine, neck, head): rotation about +X leans forward.
Left arm abducts (lifts sideways) with a negative Y rotation, right arm positive.

The animation builder layers clips (body, gesture, face) with cross-fade
blending and bakes the result into Blender actions.
"""
from __future__ import annotations

import math

from blender.motion_math import (IDENTITY, X, Y, Z, Quat, Vec, clamp, ease_in_out, ease_out_back, lerp, qslerp,
                         rot, smoothstep)

Pose = dict  # {"rot": {bone: Quat}, "loc": {bone: Vec}, "root_z": float, "root_pitch": float}

BODY_BONES = ["hips", "spine", "chest", "neck", "head", "shoulder_L", "shoulder_R", "upper_arm_L", "upper_arm_R",
              "forearm_L", "forearm_R", "hand_L", "hand_R", "thigh_L", "thigh_R", "shin_L", "shin_R",
              "foot_L", "foot_R", "foot_ik_L", "foot_ik_R", "cape_1", "cape_2", "cape_3"]
ARM_BONES = ["shoulder_L", "shoulder_R", "upper_arm_L", "upper_arm_R", "forearm_L", "forearm_R", "hand_L", "hand_R"]


def pose(rot_map: dict | None = None, loc_map: dict | None = None, root_z: float = 0.0,
         root_pitch: float = 0.0) -> Pose:
    return {"rot": rot_map or {}, "loc": loc_map or {}, "root_z": root_z, "root_pitch": root_pitch}


def ramp(t: float, dur: float, fade: float = 0.25) -> float:
    """0->1->0 envelope for gestures that should ease in and out."""
    if dur <= 0:
        return 1.0
    return smoothstep(t / fade) * smoothstep((dur - t) / fade)


def _abduct(side: str, deg: float) -> tuple[Vec, float]:
    return (Y, deg if side == "R" else -deg)


def _cape(t: float, amount: float) -> dict:
    """Cape flutter: a travelling wave down the three cape bones."""
    out = {}
    for i, b in enumerate(["cape_1", "cape_2", "cape_3"]):
        phase = t * 2 * math.pi * (1.1 + 0.5 * amount) - i * 0.9
        out[b] = rot((X, amount * (8 + 6 * i) * math.sin(phase) + amount * 12 * (i + 1) * 0.6),
                     (Y, amount * 4 * math.sin(phase * 0.7)))
    return out


# --- Body clips -------------------------------------------------------------

def idle(t: float, dur: float, p: dict) -> Pose:
    H = p["H"]
    breath = math.sin(2 * math.pi * t / 3.6 + p.get("seed", 0))
    sway = math.sin(2 * math.pi * t / 5.3 + p.get("seed", 0) * 1.7)
    r = {
        "chest": rot((X, -1.5 * breath)),
        "spine": rot((Z, 1.5 * sway)),
        "hips": rot((Z, -1.5 * sway)),
        "head": rot((X, 1.0 * breath), (Z, 3 * math.sin(2 * math.pi * t / 7.1 + p.get("seed", 0)))),
        "upper_arm_L": rot((X, 2 * breath), _abduct("L", 3 + 1.5 * sway)),
        "upper_arm_R": rot((X, 2 * breath), _abduct("R", 3 - 1.5 * sway)),
        "forearm_L": rot((X, -10)), "forearm_R": rot((X, -10)),
    }
    r.update(_cape(t, 0.25))
    return pose(r, {"hips": (0.004 * H * sway, 0, -0.004 * H * (1 + breath) * 0.5)})


def _gait(t: float, p: dict, period: float, lift: float, arm_amp: float, lean: float, bob: float,
          forearm: float) -> Pose:
    H = p["H"]
    speed = p.get("speed", 1.0)  # m/s
    stride = speed * period / 2  # distance the body travels during one stance phase
    ph_l = (t / period) % 1.0
    ph_r = (ph_l + 0.5) % 1.0
    loc: dict[str, Vec] = {}
    r: dict[str, Quat] = {}
    for side, ph in (("L", ph_l), ("R", ph_r)):
        if ph < 0.5:  # stance: foot moves back at body speed -> planted in world space
            y = -stride / 2 + stride * (ph / 0.5)
            z = 0.0
            pitch = 0.0
        else:  # swing: foot travels forward, lifted
            u = (ph - 0.5) / 0.5
            y = stride / 2 - stride * smoothstep(u)
            z = lift * H * math.sin(math.pi * u)
            pitch = -15 * math.sin(math.pi * u)
        loc[f"foot_ik_{side}"] = (0.0, y, z)
        r[f"foot_ik_{side}"] = rot((X, pitch))
    swing_l = math.cos(2 * math.pi * ph_r)  # left arm forward when right foot is forward
    swing_r = math.cos(2 * math.pi * ph_l)
    r.update({
        "upper_arm_L": rot((X, -arm_amp * swing_l), _abduct("L", 4)),
        "upper_arm_R": rot((X, -arm_amp * swing_r), _abduct("R", 4)),
        "forearm_L": rot((X, -forearm - 10 * max(0, swing_l))),
        "forearm_R": rot((X, -forearm - 10 * max(0, swing_r))),
        "hips": rot((Z, 6 * math.sin(2 * math.pi * ph_l))),
        "chest": rot((Z, -5 * math.sin(2 * math.pi * ph_l)), (X, lean * 0.5)),
        "spine": rot((X, lean)),
        "head": rot((X, -lean * 0.6)),
    })
    r.update(_cape(t, 0.6 + speed * 0.2))
    hip_z = -bob * H - 0.5 * bob * H * math.cos(4 * math.pi * ph_l)
    loc["hips"] = (0.0, 0.0, hip_z)
    return pose(r, loc)


def walk(t: float, dur: float, p: dict) -> Pose:
    return _gait(t, p, period=1.0, lift=0.07, arm_amp=22, lean=4, bob=0.022, forearm=18)


def run(t: float, dur: float, p: dict) -> Pose:
    return _gait(t, p, period=0.62, lift=0.14, arm_amp=45, lean=16, bob=0.04, forearm=80)


def fly(t: float, dur: float, p: dict) -> Pose:
    H = p["H"]
    bob = math.sin(2 * math.pi * t / 1.4)
    r = {
        "upper_arm_R": rot((X, -168), _abduct("R", 6)),
        "forearm_R": rot((X, -4)),
        "upper_arm_L": rot((X, 12), _abduct("L", 18)),
        "forearm_L": rot((X, -12)),
        "head": rot((X, -38)),
        "neck": rot((X, -12)),
        "spine": rot((X, 3 * bob)),
    }
    r.update(_cape(t * 2.2, 1.6))
    loc = {"foot_ik_L": (0, 0.03 * H, 0.03 * H), "foot_ik_R": (0, 0.16 * H, 0.14 * H),
           "hips": (0, 0, 0.004 * H * bob)}
    return pose(r, loc, root_pitch=p.get("pitch", 72))


def hero_landing(t: float, dur: float, p: dict) -> Pose:
    H = p["H"]
    u = t / max(dur, 1e-3)
    if u < 0.18:
        c = ease_out_back(u / 0.18, 0.8)
    elif u < 0.62:
        c = 1.0
    else:
        c = 1 - ease_in_out((u - 0.62) / 0.38)
    r = {
        "spine": rot((X, 32 * c)), "chest": rot((X, 12 * c)), "head": rot((X, -32 * c)),
        "upper_arm_R": rot((X, -38 * c), _abduct("R", 8 * c)), "forearm_R": rot((X, -8 * c)),
        "upper_arm_L": rot((X, 25 * c), _abduct("L", 55 * c)), "forearm_L": rot((X, -25 * c)),
    }
    r.update(_cape(t, 0.4 + 1.2 * (1 - u)))
    loc = {"hips": (0, 0.06 * H * c, -0.24 * H * c),
           "foot_ik_L": (0, -0.14 * H * c, 0), "foot_ik_R": (0, 0.2 * H * c, 0.02 * H * c)}
    return pose(r, loc)


def jump(t: float, dur: float, p: dict) -> Pose:
    H = p["H"]
    u = t / max(dur, 1e-3)
    crouch = smoothstep(u / 0.2) * (1 - smoothstep((u - 0.2) / 0.08)) + \
        smoothstep((u - 0.78) / 0.08) * (1 - smoothstep((u - 0.9) / 0.1))
    air = math.sin(math.pi * clamp((u - 0.25) / 0.53, 0, 1))
    r = {"upper_arm_L": rot(_abduct("L", 140 * air)), "upper_arm_R": rot(_abduct("R", 140 * air)),
         "spine": rot((X, 14 * crouch))}
    loc = {"hips": (0, 0, -0.1 * H * crouch), "foot_ik_L": (0, 0, 0.06 * H * air),
           "foot_ik_R": (0, 0, 0.06 * H * air)}
    r.update(_cape(t, 0.4 + air))
    return pose(r, loc, root_z=0.45 * H * air)


def sit(t: float, dur: float, p: dict) -> Pose:
    H = p["H"]
    drop = p.get("hip_height", 0.5 * H) - p.get("seat_z", 0.42)
    r = {"spine": rot((X, -4)), "upper_arm_L": rot((X, -28)), "upper_arm_R": rot((X, -28)),
         "forearm_L": rot((X, -48)), "forearm_R": rot((X, -48))}
    r.update(_cape(t, 0.2))
    loc = {"hips": (0, 0.06 * H, -drop), "foot_ik_L": (0, -0.24 * H, 0), "foot_ik_R": (0, -0.24 * H, 0)}
    return pose(r, loc)


def ride(t: float, dur: float, p: dict) -> Pose:
    H = p["H"]
    drop = p.get("hip_height", 0.5 * H) - p.get("seat_z", 0.74)
    vib = math.sin(2 * math.pi * 9 * t) * 0.0025 * H
    r = {"spine": rot((X, 22)), "head": rot((X, -18)),
         "upper_arm_L": rot((X, -62), _abduct("L", 8)), "upper_arm_R": rot((X, -62), _abduct("R", 8)),
         "forearm_L": rot((X, -22)), "forearm_R": rot((X, -22))}
    r.update(_cape(t, 1.0))
    loc = {"hips": (0, 0.02 * H, -drop + vib), "foot_ik_L": (0.04 * H, -0.1 * H, 0.18 * H),
           "foot_ik_R": (-0.04 * H, -0.1 * H, 0.18 * H)}
    return pose(r, loc)


def celebrate_body(t: float, dur: float, p: dict) -> Pose:
    H = p["H"]
    hop = abs(math.sin(2 * math.pi * t / 1.1))
    r = {"upper_arm_L": rot(_abduct("L", 150), (X, -10)), "upper_arm_R": rot(_abduct("R", 150), (X, -10)),
         "forearm_L": rot((Y, -20 * math.sin(2 * math.pi * 2 * t))),
         "forearm_R": rot((Y, 20 * math.sin(2 * math.pi * 2 * t))),
         "head": rot((X, -12))}
    r.update(_cape(t, 0.8))
    return pose(r, {"foot_ik_L": (0, 0, 0.03 * H * hop), "foot_ik_R": (0, 0, 0.03 * H * hop)},
                root_z=0.16 * H * hop)


def laugh_body(t: float, dur: float, p: dict) -> Pose:
    H = p["H"]
    b = p.get("belly", 0.0)  # round characters hold their hands out on the belly, not inside it
    shake = math.sin(2 * math.pi * 5 * t)
    r = {"chest": rot((X, -10 + 4 * shake)), "head": rot((X, -16 + 3 * shake)),
         "upper_arm_L": rot((X, -28 - 30 * b), _abduct("L", -12 + 45 * b)),
         "upper_arm_R": rot((X, -28 - 30 * b), _abduct("R", -12 + 45 * b)),
         "forearm_L": rot((X, -85 + 80 * b)), "forearm_R": rot((X, -85 + 80 * b))}
    r.update(_cape(t, 0.3))
    return pose(r, {"hips": (0, 0, -0.01 * H * abs(shake))})


def scared_body(t: float, dur: float, p: dict) -> Pose:
    H = p["H"]
    b = p.get("belly", 0.0)
    shiver = math.sin(2 * math.pi * 11 * t)
    r = {"spine": rot((X, 14)), "head": rot((X, 8), (Z, 4 * shiver)),
         "upper_arm_L": rot((X, -78), _abduct("L", -14 + 40 * b)), "upper_arm_R": rot((X, -78), _abduct("R", -14 + 40 * b)),
         "forearm_L": rot((X, -112)), "forearm_R": rot((X, -112))}
    r.update(_cape(t, 0.3))
    return pose(r, {"hips": (0.004 * H * shiver, 0.02 * H, -0.07 * H)})


# --- Gesture clips (upper body; layered over the body clip) ----------------

def talk(t: float, dur: float, p: dict) -> Pose:
    s = p.get("seed", 0)
    a = math.sin(2 * math.pi * 1.3 * t + s)
    b = math.sin(2 * math.pi * 0.9 * t + s * 2.1)
    return pose({
        "upper_arm_R": rot((X, -22 - 8 * a), _abduct("R", 10)), "forearm_R": rot((X, -55 - 15 * a)),
        "upper_arm_L": rot((X, -8 - 5 * b), _abduct("L", 6)), "forearm_L": rot((X, -30 - 10 * b)),
        "head": rot((X, 3 * math.sin(2 * math.pi * 2.1 * t)), (Z, 4 * b)),
    })


def talk_open(t: float, dur: float, p: dict) -> Pose:
    a = math.sin(2 * math.pi * 1.1 * t + p.get("seed", 0))
    return pose({
        "upper_arm_L": rot((X, -30), _abduct("L", 38 + 6 * a)), "upper_arm_R": rot((X, -30), _abduct("R", 38 + 6 * a)),
        "forearm_L": rot((X, -55 - 8 * a)), "forearm_R": rot((X, -55 - 8 * a)),
        "head": rot((X, -4 + 3 * a)),
    })


def point(t: float, dur: float, p: dict) -> Pose:
    jab = math.exp(-4 * t) * math.sin(2 * math.pi * 3 * t)
    return pose({
        "upper_arm_R": rot((X, -84 - 6 * jab), _abduct("R", 12)), "forearm_R": rot((X, -6)),
        "hand_R": rot((X, 8)), "chest": rot((Z, 10)), "head": rot((X, -4)),
        "upper_arm_L": rot((X, -5), _abduct("L", 8)), "forearm_L": rot((X, -25)),
    })


def threaten(t: float, dur: float, p: dict) -> Pose:
    b = p.get("belly", 0.0)
    shake = math.sin(2 * math.pi * 4.2 * t)
    return pose({
        "upper_arm_R": rot((X, -62), _abduct("R", 22 + 20 * b)), "forearm_R": rot((X, -105 + 16 * shake)),
        "upper_arm_L": rot((X, 10), _abduct("L", 28 + 40 * b)), "forearm_L": rot((Y, 70 - 90 * b), (X, -40)),
        "chest": rot((X, 9)), "head": rot((X, -6 + 2 * shake)),
    })


def wave(t: float, dur: float, p: dict) -> Pose:
    w = math.sin(2 * math.pi * 2.4 * t)
    return pose({
        "upper_arm_R": rot(_abduct("R", 148), (X, -12)), "forearm_R": rot((Y, 24 * w)),
        "hand_R": rot((Y, 12 * w)), "head": rot((Z, 6), (X, -3)),
    })


def clap(t: float, dur: float, p: dict) -> Pose:
    b = p.get("belly", 0.0)
    c = abs(math.sin(2 * math.pi * 2.2 * t))
    return pose({
        "upper_arm_L": rot((X, -52 - 40 * b), _abduct("L", -16 + 30 * b)),
        "upper_arm_R": rot((X, -52 - 40 * b), _abduct("R", -16 + 30 * b)),
        "forearm_L": rot((X, -58), (Z, -28 * c)), "forearm_R": rot((X, -58), (Z, 28 * c)),
        "head": rot((X, -5)),
    })


def hands_on_hips(t: float, dur: float, p: dict) -> Pose:
    b = p.get("belly", 0.0)
    return pose({
        "upper_arm_L": rot(_abduct("L", 46 + 25 * b), (X, 8)), "upper_arm_R": rot(_abduct("R", 46 + 25 * b), (X, 8)),
        "forearm_L": rot(_abduct("L", -105 + 70 * b)), "forearm_R": rot(_abduct("R", -105 + 70 * b)),
        "chest": rot((X, -5)), "head": rot((X, -5)),
    })


def work(t: float, dur: float, p: dict) -> Pose:
    u = (t * 1.3) % 1.0
    lift = smoothstep(u / 0.65) if u < 0.65 else 1 - smoothstep((u - 0.65) / 0.2)
    return pose({
        "upper_arm_R": rot((X, -35 - 70 * lift), _abduct("R", 12)), "forearm_R": rot((X, -70 + 40 * lift)),
        "upper_arm_L": rot((X, -40)), "forearm_L": rot((X, -50)),
        "spine": rot((X, 12)), "head": rot((X, 18)),
    })


def look_around(t: float, dur: float, p: dict) -> Pose:
    sweep = math.sin(2 * math.pi * t / 2.2)
    return pose({"head": rot((Z, 48 * sweep), (X, -4)), "chest": rot((Z, 14 * sweep)),
                 "upper_arm_R": rot((X, -128), _abduct("R", 30)), "forearm_R": rot((X, -105))})


def power_up(t: float, dur: float, p: dict) -> Pose:
    shiver = math.sin(2 * math.pi * 9 * t) * 2
    return pose({
        "upper_arm_L": rot((X, -86), _abduct("L", -8)), "upper_arm_R": rot((X, -86), _abduct("R", -8)),
        "forearm_L": rot((X, -4 + shiver)), "forearm_R": rot((X, -4 - shiver)),
        "hand_L": rot((X, 55)), "hand_R": rot((X, 55)), "chest": rot((X, -6)), "head": rot((X, -6)),
    })


def surprised(t: float, dur: float, p: dict) -> Pose:
    return pose({
        "upper_arm_L": rot((X, -22), _abduct("L", 58)), "upper_arm_R": rot((X, -22), _abduct("R", 58)),
        "forearm_L": rot((X, -62)), "forearm_R": rot((X, -62)), "chest": rot((X, -9)), "head": rot((X, -10)),
    })


def scared(t: float, dur: float, p: dict) -> Pose:
    b = p.get("belly", 0.0)
    sh = math.sin(2 * math.pi * 11 * t)
    return pose({
        "upper_arm_L": rot((X, -78), _abduct("L", -14 + 40 * b)), "upper_arm_R": rot((X, -78), _abduct("R", -14 + 40 * b)),
        "forearm_L": rot((X, -112)), "forearm_R": rot((X, -112)), "head": rot((X, 8), (Z, 4 * sh)),
    })


def laugh(t: float, dur: float, p: dict) -> Pose:
    full = laugh_body(t, dur, p)
    full["loc"] = {}
    return full


BODY_CLIPS = {
    "idle": idle, "walk": walk, "run": run, "fly": fly, "hero_landing": hero_landing, "jump": jump,
    "sit": sit, "ride": ride, "celebrate": celebrate_body, "laugh_body": laugh_body, "scared_body": scared_body,
}
GESTURE_CLIPS = {
    "talk": talk, "talk_open": talk_open, "point": point, "threaten": threaten, "wave": wave, "clap": clap,
    "hands_on_hips": hands_on_hips, "work": work, "look_around": look_around, "power_up": power_up,
    "surprised": surprised, "scared": scared, "laugh": laugh,
}

# Face presets: shape key values and brow-bone offsets (in head-height units).
EXPRESSIONS: dict[str, dict] = {
    "neutral":   {"Smile": 0.15, "Frown": 0.0, "Squint": 0.0, "Round": 0.0, "Open": 0.0, "brow_up": 0.0, "brow_tilt": 0},
    "happy":     {"Smile": 0.85, "Frown": 0.0, "Squint": 0.15, "Round": 0.0, "Open": 0.1, "brow_up": 0.35, "brow_tilt": 0},
    "sad":       {"Smile": 0.0, "Frown": 0.75, "Squint": 0.25, "Round": 0.0, "Open": 0.0, "brow_up": 0.2, "brow_tilt": -18},
    "angry":     {"Smile": 0.0, "Frown": 0.55, "Squint": 0.35, "Round": 0.0, "Open": 0.05, "brow_up": -0.4, "brow_tilt": 22},
    "surprised": {"Smile": 0.0, "Frown": 0.0, "Squint": 0.0, "Round": 0.55, "Open": 0.3, "brow_up": 1.0, "brow_tilt": -5},
    "scared":    {"Smile": 0.0, "Frown": 0.45, "Squint": 0.0, "Round": 0.2, "Open": 0.25, "brow_up": 0.7, "brow_tilt": -16},
    "confident": {"Smile": 0.55, "Frown": 0.0, "Squint": 0.2, "Round": 0.0, "Open": 0.0, "brow_up": 0.15, "brow_tilt": 8},
    "laughing":  {"Smile": 1.0, "Frown": 0.0, "Squint": 0.5, "Round": 0.0, "Open": 0.35, "brow_up": 0.4, "brow_tilt": -4},
}

# Which talking gesture suits each emotion.
TALK_GESTURE = {
    "neutral": "talk", "happy": "talk_open", "sad": "talk", "angry": "threaten", "surprised": "surprised",
    "scared": "scared", "confident": "hands_on_hips", "laughing": "laugh",
}


def blend_poses(a: Pose, b: Pose, w: float, mask: list[str] | None = None) -> Pose:
    """Blend pose ``b`` over ``a`` with weight ``w``.

    Rotations use quaternion slerp, locations lerp. With a ``mask`` only those
    bones are affected (layering); otherwise every bone in either pose blends.
    """
    if w <= 0:
        return a
    out = {"rot": dict(a["rot"]), "loc": dict(a["loc"]),
           "root_z": lerp(a.get("root_z", 0), b.get("root_z", 0), w) if mask is None else a.get("root_z", 0),
           "root_pitch": lerp(a.get("root_pitch", 0), b.get("root_pitch", 0), w) if mask is None
           else a.get("root_pitch", 0)}
    bones = set(b["rot"]) | (set(a["rot"]) if mask is None else set())
    for bone in bones:
        if mask is not None and bone not in mask:
            continue
        qa = a["rot"].get(bone, IDENTITY)
        qb = b["rot"].get(bone, IDENTITY)
        out["rot"][bone] = qslerp(qa, qb, w)
    lbones = set(b["loc"]) | (set(a["loc"]) if mask is None else set())
    for bone in lbones:
        if mask is not None and bone not in mask:
            continue
        la = a["loc"].get(bone, (0.0, 0.0, 0.0))
        lb = b["loc"].get(bone, (0.0, 0.0, 0.0))
        out["loc"][bone] = (lerp(la[0], lb[0], w), lerp(la[1], lb[1], w), lerp(la[2], lb[2], w))
    return out
