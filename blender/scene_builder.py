"""Assemble one animated 3D scene from a scene direction (run inside Blender).

Steps: environment -> append character assets (same .blend for every scene)
-> bake character animation -> props and effects -> camera -> render settings.
"""
from __future__ import annotations

import json
import math

import bpy

from blender.animation_builder import CharacterBaker, write_curve
from blender.camera_builder import build_camera
from blender.environment_builder import EnvironmentBuilder
from blender.material_builder import glow_material, material
from blender.mesh_utils import MeshBuilder
from blender.motion_math import sample_path
from blender.render_settings import configure_render


def append_character(cid: str, blend_path: str):
    """Append collection CHR_<cid> from the character library file."""
    with bpy.data.libraries.load(blend_path, link=False) as (src, dst):
        dst.collections = [c for c in src.collections if c == f"CHR_{cid}"]
    coll = dst.collections[0]
    bpy.context.scene.collection.children.link(coll)
    objs = {"rig": None, "face": None, "body": None, "cape": None}
    for o in coll.objects:
        if o.type == "ARMATURE":
            objs["rig"] = o
        elif o.name.startswith(f"{cid}_face"):
            objs["face"] = o
        elif o.name.startswith(f"{cid}_body"):
            objs["body"] = o
        elif o.name.startswith(f"{cid}_cape"):
            objs["cape"] = o
    return coll, objs


def _key_scale(obj, keys: list[tuple[int, float]]) -> None:
    for frame, s in keys:
        obj.scale = (s, s, s)
        obj.keyframe_insert("scale", frame=frame)


def add_effects(effects: list[dict], rigs: dict, coll, fps: int) -> None:
    for i, fx in enumerate(effects):
        rig = rigs.get(fx.get("character"))
        start, end = int(fx["start"]), int(fx["end"])
        H = json.loads(rig["dims"])["H"] if rig else 1.5
        if fx["type"] == "energy_shield" and rig:
            mb = MeshBuilder(f"fx_shield_{i}")
            mb.sphere((0, 0, 0), (0.75 * H, 0.75 * H, 0.68 * H), glow_material("fx_shield", (0.35, 0.85, 1.0), 1.4, 0.06),
                      segs=32, rings=16)
            obj = mb.to_object(coll, parent=rig)
            obj.location = (0, 0, 0.5 * H)
            obj.visible_shadow = False
            keys = [(start - 1, 0.0), (start, 0.01), (start + 8, 1.12), (start + 12, 1.0)]
            f = start + 18
            while f < end - 12:
                keys.append((f, 1.04 if (f // 9) % 2 else 0.97))
                f += 9
            keys += [(end - 8, 1.0), (end, 0.0)]
            _key_scale(obj, keys)
            _flash(coll, rig, (0.3, 0.85, 1.0), start, end, 1.0 * H, 400)
        elif fx["type"] == "power_up" and rig:
            mb = MeshBuilder(f"fx_power_{i}")
            mb.torus((0, 0, 0), 0.5 * H, 0.03 * H, glow_material("fx_power", (1.0, 0.85, 0.2), 6.0, 0.5),
                     segs=32, ring_segs=8)
            obj = mb.to_object(coll, parent=rig)
            obj.location = (0, 0, 0.55 * H)
            obj.visible_shadow = False
            _key_scale(obj, [(start - 1, 0.0), (start, 0.2), (start + 10, 1.4), (start + 18, 0.6),
                             (start + 26, 1.5), (end, 0.0)])
            _flash(coll, rig, (1.0, 0.85, 0.3), start, end, 0.6 * H, 300)
        elif fx["type"] == "landing_impact":
            mb = MeshBuilder(f"fx_impact_{i}")
            mb.torus((0, 0, 0), 0.6, 0.035, material("fx_dust", (0.8, 0.72, 0.6), roughness=1.0), segs=32,
                     ring_segs=6, scale=(1.0, 1.0, 0.5))
            obj = mb.to_object(coll)
            obj.location = (fx["x"], fx["y"], 0.05)
            obj.visible_shadow = False
            _key_scale(obj, [(start - 1, 0.0), (start, 0.1), (start + int(0.5 * fps), 1.8),
                             (start + int(0.7 * fps), 0.0)])


def _flash(coll, rig, color, start: int, end: int, z: float, energy: float) -> None:
    d = bpy.data.lights.new(f"fx_light_{start}", "POINT")
    d.color = color
    d.shadow_soft_size = 0.5
    d.use_shadow = False
    lo = bpy.data.objects.new(f"fx_light_{start}", d)
    lo.parent = rig
    lo.location = (0, -0.6, z)
    coll.objects.link(lo)
    for frame, e in ((start - 1, 0.0), (start + 6, energy * 1.6), (start + 14, energy), (end - 6, energy),
                     (end, 0.0)):
        d.energy = e
        d.keyframe_insert("energy", frame=frame)


def add_props(props: list[dict], directions: dict, coll, n_frames: int) -> None:
    env = EnvironmentBuilder("city_road", coll)
    for i, p in enumerate(props):
        if p["type"] != "motorcycle":
            continue
        bike = env.motorcycle(f"prop_bike_{i}", color=tuple(p.get("color", (0.1, 0.35, 0.85))))
        path = directions[p["character"]]["path"]
        start, end = int(p["start"]), int(p["end"])
        loc = [[], [], []]
        yaw = []
        for f in range(n_frames):
            ff = min(max(f, start), end)
            s = sample_path(path, ff)
            loc[0].append(s["x"])
            loc[1].append(s["y"] + 0.12)
            loc[2].append(0.0)
            yaw.append(math.radians(s["yaw"]))
        bike.rotation_mode = "XYZ"
        for k in range(3):
            write_curve(bike, "location", k, loc[k])
        write_curve(bike, "rotation_euler", 2, yaw)


def build_scene(job: dict) -> None:
    sd = job["scene"]
    fps = job.get("fps", 24)
    n = int(sd["frame_count"])
    scene = bpy.context.scene
    scene.name = f"scene_{sd['id']:03d}"
    scene.frame_start, scene.frame_end = 0, n - 1
    scene.render.fps = fps

    env_coll = bpy.data.collections.new("ENVIRONMENT")
    scene.collection.children.link(env_coll)
    EnvironmentBuilder(sd["location"], env_coll, seed=sd.get("env_seed", 1), backdrop=job.get("backdrop")).build()

    fx_coll = bpy.data.collections.new("FX_PROPS_CAMERA")
    scene.collection.children.link(fx_coll)
    rigs = {}
    directions = {c["id"]: c for c in sd["characters"]}
    for c in sd["characters"]:
        _, objs = append_character(c["id"], job["character_assets"][c["id"]])
        rig = objs["rig"]
        rigs[c["id"]] = rig
        CharacterBaker(rig, objs["face"], c, sd, fps).bake(n)
    add_props(sd.get("props", []), directions, fx_coll, n)
    add_effects(sd.get("effects", []), rigs, fx_coll, fps)
    build_camera(scene, sd["camera_shots"], n, fx_coll)

    configure_render(scene, quality=job.get("quality", "standard"), engine=job.get("engine", "BLENDER_EEVEE_NEXT"),
                     fps=fps, use_gpu=job.get("use_gpu", False))
    scene.render.image_settings.file_format = "JPEG"
    scene.render.image_settings.quality = job.get("jpeg_quality", 92)
    scene.render.filepath = job["frames_dir"].rstrip("/") + "/frame_"
    scene.render.use_file_extension = True
    scene.render.use_overwrite = False  # resume: frames already on disk are skipped
    scene.render.use_placeholder = False
    scene["leo_scene"] = json.dumps({"id": sd["id"], "title": sd["title"], "frames": n,
                                     "characters": [c["id"] for c in sd["characters"]]})
