"""Blender entry point: render single layout keyframes for the AI video mode.

Usage: blender -b scene_001.blend -P blender/run_render_keyframes.py -- job.json
job.json: {"frames": [12, 80, ...], "out_dir": "...", "quality": "standard"}
Writes key_<frame>.png and prints ``LEO_FRAME <done> <total>``.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bpy  # noqa: E402

from blender.render_settings import configure_render  # noqa: E402

job = json.load(open(sys.argv[sys.argv.index("--") + 1], encoding="utf-8"))
scene = bpy.context.scene
configure_render(scene, quality=job.get("quality", "standard"), fps=scene.render.fps)
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
frames = job["frames"]
for i, f in enumerate(frames, start=1):
    scene.frame_set(int(f))
    scene.render.filepath = os.path.join(job["out_dir"], f"key_{int(f):05d}.png")
    bpy.ops.render.render(write_still=True)
    print(f"LEO_FRAME {i} {len(frames)}", flush=True)
sys.stdout.flush()
os._exit(0)
