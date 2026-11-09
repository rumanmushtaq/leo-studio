"""Blender entry point: render the open scene file frame by frame.

Usage: blender -b scene_001.blend -P blender/run_render_scene.py -- [engine]
Frames already on disk are skipped (resume after cancel). Prints
``LEO_FRAME <frame> <total>`` after each frame is written.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bpy  # noqa: E402

scene = bpy.context.scene
args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if args and args[0] in ("BLENDER_EEVEE_NEXT", "BLENDER_WORKBENCH", "CYCLES"):
    from blender.render_settings import configure_render  # noqa: E402

    quality = args[1] if len(args) > 1 else "standard"
    configure_render(scene, quality=quality, engine=args[0], fps=scene.render.fps)
total = scene.frame_end - scene.frame_start + 1


def _post(sc, *_):
    print(f"LEO_FRAME {sc.frame_current - sc.frame_start + 1} {total}", flush=True)


bpy.app.handlers.render_post.append(_post)
bpy.ops.render.render(animation=True)
print("LEO_RENDER_DONE", flush=True)
# Skip Blender's normal shutdown: on some iGPU drivers / power-saver profiles it can hang
# after the last frame is already on disk.
sys.stdout.flush()
os._exit(0)
