"""Blender entry point: build character assets.

Usage: blender -b --factory-startup -P blender/run_build_characters.py -- job.json
job.json: {"characters": [{"id", "spec", "blend_path", "reference_path"}], "reference_size": 512}
Prints ``LEO_PROGRESS <done>/<total> <id>`` after each character.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

from blender.character_builder import build_character  # noqa: E402
from blender.render_settings import configure_render  # noqa: E402


def reset_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def reference_render(rig, path: str, size: int) -> None:
    """3/4 front portrait of the character on a neutral backdrop."""
    scene = bpy.context.scene
    dims = json.loads(rig["dims"])
    H = dims["H"]
    ref = bpy.data.collections.new("REFERENCE_SETUP")
    scene.collection.children.link(ref)
    cam_data = bpy.data.cameras.new("ref_cam")
    cam_data.lens = 50
    cam = bpy.data.objects.new("ref_cam", cam_data)
    ref.objects.link(cam)
    target = Vector((0, 0, H * 0.52))
    cam.location = Vector((H * 0.75, -H * 1.75, H * 0.7))
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam
    for name, loc, energy in (("key", (2, -3, 4), 5.5), ("fill", (-3, -2, 2), 2.5), ("rim", (-1, 4, 3), 2.5)):
        ld = bpy.data.lights.new(name, "SUN")
        ld.energy = energy
        lo = bpy.data.objects.new(name, ld)
        lo.rotation_euler = (Vector((0, 0, 0)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        ref.objects.link(lo)
    world = bpy.data.worlds.new("ref_world")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.55, 0.62, 0.72, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 1.4
    scene.world = world
    configure_render(scene, quality="standard", width=size, height=size)
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    # Keep the saved asset clean: remove the temporary camera/lights.
    for obj in list(ref.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.collections.remove(ref)


def main() -> None:
    job = json.load(open(sys.argv[sys.argv.index("--") + 1], encoding="utf-8"))
    chars = job["characters"]
    for i, c in enumerate(chars, start=1):
        reset_scene()
        coll = bpy.data.collections.new(f"CHR_{c['id']}")
        bpy.context.scene.collection.children.link(coll)
        rig = build_character(c["id"], c["spec"], coll)
        if c.get("reference_path"):
            reference_render(rig, c["reference_path"], job.get("reference_size", 512))
        os.makedirs(os.path.dirname(c["blend_path"]), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=c["blend_path"], compress=True)
        print(f"LEO_PROGRESS {i}/{len(chars)} {c['id']}", flush=True)


if __name__ == "__main__":
    main()
