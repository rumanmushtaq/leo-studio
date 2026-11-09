"""Shared render configuration for EEVEE / Workbench / Cycles (run inside Blender)."""
from __future__ import annotations

import bpy

QUALITY = {
    "preview": {"percent": 50, "samples": 1, "shadows": False},
    "standard": {"percent": 100, "samples": 4, "shadows": True},
    "high": {"percent": 100, "samples": 16, "shadows": True},
}


def configure_render(scene, quality: str = "standard", width: int = 1280, height: int = 720,
                     engine: str = "BLENDER_EEVEE_NEXT", fps: int = 24, use_gpu: bool = False) -> None:
    q = QUALITY.get(quality, QUALITY["standard"])
    r = scene.render
    r.engine = engine
    r.resolution_x, r.resolution_y = width, height
    r.resolution_percentage = q["percent"]
    r.fps = fps
    r.fps_base = 1.0
    r.film_transparent = False
    r.use_motion_blur = False
    # AgX with the "Punchy" look: soft highlight roll-off like feature animation, saturated mids
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Punchy"
    scene.view_settings.exposure = 0.25
    scene.view_settings.gamma = 1.0
    if engine == "BLENDER_EEVEE_NEXT":
        ee = scene.eevee
        ee.taa_render_samples = q["samples"]
        ee.use_shadows = q["shadows"]
        ee.shadow_ray_count = 1
        ee.shadow_step_count = 4 if q["shadows"] else 1
        ee.use_raytracing = False
        ee.use_volumetric_shadows = False
        ee.fast_gi_method = "AMBIENT_OCCLUSION_ONLY"
        ee.use_fast_gi = quality != "preview"
        ee.fast_gi_distance = 1.5
        ee.use_bokeh_jittered = False
    elif engine == "BLENDER_WORKBENCH":
        sh = scene.display.shading
        sh.light = "STUDIO"
        sh.color_type = "MATERIAL"
        sh.show_shadows = q["shadows"]
        sh.show_cavity = True
        sh.show_backface_culling = True  # hides the inverted-hull outline shell from the inside
        scene.display.render_aa = "8" if quality != "preview" else "FXAA"
    elif engine == "CYCLES":
        scene.cycles.samples = {"preview": 16, "standard": 48, "high": 128}.get(quality, 48)
        scene.cycles.use_denoising = True
        if use_gpu:
            prefs = bpy.context.preferences.addons["cycles"].preferences
            for backend in ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL"):
                try:
                    prefs.compute_device_type = backend
                    prefs.get_devices()
                    if any(d.type == backend for d in prefs.devices):
                        for d in prefs.devices:
                            d.use = True
                        scene.cycles.device = "GPU"
                        break
                except TypeError:
                    continue
