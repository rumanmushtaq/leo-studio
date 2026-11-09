"""Blender entry point: build and save one scene .blend.

Usage: blender -b --factory-startup -P blender/run_build_scene.py -- job.json
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bpy  # noqa: E402

from blender.scene_builder import build_scene  # noqa: E402


def main() -> None:
    job = json.load(open(sys.argv[sys.argv.index("--") + 1], encoding="utf-8"))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    build_scene(job)
    os.makedirs(os.path.dirname(job["out_blend"]), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=job["out_blend"], compress=True)
    print("LEO_SCENE_SAVED", job["out_blend"], flush=True)


if __name__ == "__main__":
    main()
