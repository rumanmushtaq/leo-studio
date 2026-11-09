"""Pure-Python math shared by the host app and Blender's bundled Python.

No bpy / numpy imports: this module is imported on both sides so camera
planning (host) and animation baking (Blender) sample paths identically.
Quaternions are (w, x, y, z) tuples.
"""
from __future__ import annotations

import math

Quat = tuple[float, float, float, float]
Vec = tuple[float, float, float]

IDENTITY: Quat = (1.0, 0.0, 0.0, 0.0)


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def smoothstep(t: float) -> float:
    t = clamp(t, 0.0, 1.0)
    return t * t * (3 - 2 * t)


def ease_in_out(t: float) -> float:
    t = clamp(t, 0.0, 1.0)
    return 0.5 - 0.5 * math.cos(math.pi * t)


def ease_out_back(t: float, s: float = 1.4) -> float:
    t = clamp(t, 0.0, 1.0) - 1
    return t * t * ((s + 1) * t + s) + 1


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def vlerp(a: Vec, b: Vec, t: float) -> Vec:
    return (lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2], b[2], t))


def vadd(a: Vec, b: Vec) -> Vec:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def vscale(a: Vec, s: float) -> Vec:
    return (a[0] * s, a[1] * s, a[2] * s)


def axis_angle(axis: Vec, degrees: float) -> Quat:
    x, y, z = axis
    n = math.sqrt(x * x + y * y + z * z) or 1.0
    h = math.radians(degrees) / 2
    s = math.sin(h) / n
    return (math.cos(h), x * s, y * s, z * s)


def qmul(a: Quat, b: Quat) -> Quat:
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (aw * bw - ax * bx - ay * by - az * bz,
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw)


def qnormalize(q: Quat) -> Quat:
    n = math.sqrt(sum(c * c for c in q)) or 1.0
    return (q[0] / n, q[1] / n, q[2] / n, q[3] / n)


def qslerp(a: Quat, b: Quat, t: float) -> Quat:
    dot = sum(x * y for x, y in zip(a, b))
    if dot < 0:
        b, dot = tuple(-c for c in b), -dot
    if dot > 0.9995:
        return qnormalize(tuple(x + (y - x) * t for x, y in zip(a, b)))
    th0 = math.acos(clamp(dot, -1.0, 1.0))
    th = th0 * t
    s0 = math.cos(th) - dot * math.sin(th) / math.sin(th0)
    s1 = math.sin(th) / math.sin(th0)
    return tuple(s0 * x + s1 * y for x, y in zip(a, b))  # type: ignore[return-value]


def rot(*pairs: tuple[Vec, float]) -> Quat:
    """Compose rotations given as (axis, degrees) in armature space."""
    q = IDENTITY
    for axis, deg in pairs:
        if abs(deg) > 1e-6:
            q = qmul(axis_angle(axis, deg), q)
    return q


X: Vec = (1.0, 0.0, 0.0)
Y: Vec = (0.0, 1.0, 0.0)
Z: Vec = (0.0, 0.0, 1.0)


# --- Root-motion paths -------------------------------------------------------
# A path is a list of keys: {"frame", "x", "y", "z", "yaw", "pitch", "ease"}.
# "ease" applies to the segment that *ends* at that key: linear | smooth | arc.

def sample_path(keys: list[dict], frame: float) -> dict:
    if not keys:
        return {"x": 0.0, "y": 0.0, "z": 0.0, "yaw": 0.0, "pitch": 0.0, "speed": 0.0}
    if frame <= keys[0]["frame"]:
        return {**_key_vals(keys[0]), "speed": 0.0}
    if frame >= keys[-1]["frame"]:
        return {**_key_vals(keys[-1]), "speed": 0.0}
    for a, b in zip(keys, keys[1:]):
        if a["frame"] <= frame <= b["frame"]:
            span = max(1e-6, b["frame"] - a["frame"])
            u = (frame - a["frame"]) / span
            ease = b.get("ease", "linear")
            w = smoothstep(u) if ease == "smooth" else u
            va, vb = _key_vals(a), _key_vals(b)
            out = {k: lerp(va[k], vb[k], w) for k in va}
            if ease == "arc":  # flight: drop in along a curve, fast first then settling
                w2 = 1 - (1 - u) ** 2
                out["x"] = lerp(va["x"], vb["x"], w2)
                out["y"] = lerp(va["y"], vb["y"], w2)
                out["z"] = lerp(va["z"], vb["z"], u ** 0.6 if vb["z"] < va["z"] else u)
            dist = math.dist((va["x"], va["y"]), (vb["x"], vb["y"]))
            out["speed"] = dist / span  # metres per frame (segment average)
            return out
    return {**_key_vals(keys[-1]), "speed": 0.0}


def _key_vals(k: dict) -> dict:
    return {"x": float(k.get("x", 0)), "y": float(k.get("y", 0)), "z": float(k.get("z", 0)),
            "yaw": float(k.get("yaw", 0)), "pitch": float(k.get("pitch", 0))}


def yaw_towards(dx: float, dy: float) -> float:
    """Yaw (degrees) that turns a character facing -Y toward direction (dx, dy)."""
    return math.degrees(math.atan2(dx, -dy))
