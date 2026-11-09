"""Procedural low-poly 3D environments (run inside Blender).

Layout convention: the acting area is x in [-7, 7], y in [-2.5, 2.5]; cameras
sit at negative y looking toward +y. Builders keep that zone and the camera
side (y < -2.5, |x| < 8) free of tall props; backdrops live at y >= 3.5.
Each environment returns named "marker" empties for cameras and props that
the scene builder can use (e.g. where a parked car is).
"""
from __future__ import annotations

import math
from pathlib import Path
import random

import bpy
from mathutils import Matrix

from blender.material_builder import gradient_sky_material, material, srgb_to_linear
from blender.mesh_utils import MeshBuilder

ENV_STYLE = {
    "construction_site": {"ground": (0.55, 0.42, 0.28), "horizon": (0.98, 0.86, 0.7), "zenith": (0.35, 0.6, 0.95),
                          "sun": (52, 35), "sun_color": (1.0, 0.95, 0.85)},
    "city_road": {"ground": (0.42, 0.62, 0.32), "horizon": (0.9, 0.93, 0.98), "zenith": (0.3, 0.55, 0.95),
                  "sun": (55, -30), "sun_color": (1.0, 0.97, 0.9)},
    "motorcycle_garage": {"ground": (0.5, 0.5, 0.52), "horizon": (0.95, 0.88, 0.8), "zenith": (0.35, 0.55, 0.9),
                          "sun": (50, 20), "sun_color": (1.0, 0.93, 0.85)},
    "car_workshop": {"ground": (0.5, 0.5, 0.52), "horizon": (0.95, 0.9, 0.82), "zenith": (0.38, 0.58, 0.92),
                     "sun": (48, -25), "sun_color": (1.0, 0.94, 0.85)},
    "house": {"ground": (0.4, 0.66, 0.32), "horizon": (0.95, 0.92, 0.85), "zenith": (0.35, 0.6, 0.95),
              "sun": (50, 30), "sun_color": (1.0, 0.95, 0.88)},
    "school": {"ground": (0.42, 0.68, 0.33), "horizon": (0.92, 0.94, 0.98), "zenith": (0.32, 0.58, 0.96),
               "sun": (58, 10), "sun_color": (1.0, 0.97, 0.92)},
    "police_station": {"ground": (0.45, 0.46, 0.5), "horizon": (0.9, 0.92, 0.96), "zenith": (0.3, 0.5, 0.88),
                       "sun": (55, -20), "sun_color": (1.0, 0.97, 0.92)},
    "park": {"ground": (0.36, 0.7, 0.3), "horizon": (0.98, 0.92, 0.82), "zenith": (0.35, 0.65, 0.98),
             "sun": (40, 40), "sun_color": (1.0, 0.92, 0.8)},
    "hideout": {"ground": (0.42, 0.36, 0.34), "horizon": (0.45, 0.38, 0.5), "zenith": (0.3, 0.26, 0.42),
                "sun": (65, 15), "sun_color": (0.85, 0.78, 1.0), "interior": True},
    "village": {"ground": (0.78, 0.64, 0.46), "horizon": (1.0, 0.9, 0.75), "zenith": (0.38, 0.64, 0.95),
                "sun": (38, 35), "sun_color": (1.0, 0.92, 0.78)},
    "shop": {"ground": (0.6, 0.58, 0.55), "horizon": (0.97, 0.9, 0.8), "zenith": (0.35, 0.6, 0.95),
             "sun": (50, 25), "sun_color": (1.0, 0.95, 0.86)},
}

BUILDING_COLORS = [(0.93, 0.78, 0.55), (0.75, 0.55, 0.45), (0.85, 0.85, 0.8), (0.6, 0.72, 0.85),
                   (0.92, 0.65, 0.5), (0.7, 0.8, 0.65), (0.95, 0.9, 0.7)]


class EnvironmentBuilder:
    def __init__(self, env_type: str, collection, seed: int = 1, backdrop: str | None = None):
        self.backdrop = backdrop if backdrop and Path(backdrop).exists() else None
        self.type = env_type if env_type in ENV_STYLE else "city_road"
        self.style = ENV_STYLE[self.type]
        self.coll = collection
        self.rng = random.Random(seed)
        self.mb = MeshBuilder(f"env_{self.type}_static")
        self.markers: dict[str, tuple] = {}
        self.dynamic: list[bpy.types.Object] = []

    def m(self, name: str, color, **kw):
        return material(f"env_{name}", color, **kw)

    # ------------------------------------------------------------ primitives
    def box(self, center, size, color_name: str, color, **kw):
        self.mb.box(center, size, self.m(color_name, color, **kw))

    def building(self, x: float, y: float, w: float, d: float, h: float, color=None, roof: str = "flat",
                 windows: bool = True, sign: str | None = None) -> None:
        color = color or self.rng.choice(BUILDING_COLORS)
        cname = "bld_%d%d%d" % tuple(int(c * 9) for c in color)
        self.box((x, y, h / 2), (w, d, h), cname, color, roughness=0.85)
        if roof == "gable":
            mb = self.mb
            mat = self.m("roof_red", (0.7, 0.22, 0.15), roughness=0.7)
            m = Matrix.Translation((x, y, h)) @ Matrix.Rotation(math.pi / 2, 4, "Y")
            mb.cylinder(None, d * 0.75, w * 1.08, mat, segs=3, matrix=m @ Matrix.Rotation(math.pi / 2, 4, "Z")
                        @ Matrix.Diagonal((1.0, 0.65, 1.0, 1.0)))
        else:
            self.box((x, y, h + 0.08), (w + 0.2, d + 0.2, 0.16), "trim", (0.95, 0.95, 0.92))
        if windows:
            win = self.m("window", (0.55, 0.75, 0.95), roughness=0.08, metallic=0.3, emission=0.15)
            rows = max(1, int((h - 1.2) // 1.6))
            cols = max(1, int(w // 1.6))
            for r_ in range(rows):
                for c_ in range(cols):
                    wx = x - w / 2 + (c_ + 0.5) * w / cols
                    wz = 1.5 + r_ * 1.6
                    if wz + 0.5 < h:
                        self.mb.box((wx, y - d / 2 - 0.02, wz), (0.8, 0.06, 0.9), win)
        if sign:
            self.text(sign, (x, y - d / 2 - 0.08, min(h - 0.5, 3.4)), size=0.55)

    def text(self, body: str, loc, size: float = 0.6, color=(0.95, 0.2, 0.15)) -> None:
        curve = bpy.data.curves.new(f"sign_{body}", "FONT")
        curve.body = body
        curve.size = size
        curve.extrude = 0.03
        curve.align_x = "CENTER"
        obj = bpy.data.objects.new(f"sign_{body}", curve)
        obj.location = loc
        obj.rotation_euler = (math.pi / 2, 0, 0)
        obj.data.materials.append(self.m("sign_" + body.lower(), color, emission=0.3))
        self.coll.objects.link(obj)

    def tree(self, x: float, y: float, s: float = 1.0) -> None:
        self.mb.capsule((x, y, 0), (x, y, 1.6 * s), 0.14 * s, 0.1 * s, self.m("bark", (0.4, 0.26, 0.15)), segs=8)
        leaf = self.m("leaf", (0.25, 0.6, 0.22), roughness=0.8)
        for dx, dz, rr in ((0, 2.2, 0.9), (0.45, 1.9, 0.6), (-0.45, 1.95, 0.65)):
            self.mb.sphere((x + dx * s, y, dz * s), (rr * s, rr * s, rr * 0.9 * s), leaf, segs=12, rings=8)

    def streetlight(self, x: float, y: float) -> None:
        pole = self.m("pole", (0.25, 0.27, 0.3), metallic=0.6, roughness=0.4)
        self.mb.capsule((x, y, 0), (x, y, 4.2), 0.07, 0.06, pole, segs=8, caps=False)
        self.mb.capsule((x, y, 4.2), (x + 0.7, y, 4.35), 0.05, 0.05, pole, segs=8)
        self.mb.sphere((x + 0.8, y, 4.25), (0.22, 0.22, 0.12), self.m("lamp", (1, 0.95, 0.75), emission=2.0))

    def car(self, x: float, y: float, color=(0.85, 0.15, 0.15), yaw: float = 0.0, name: str | None = None):
        """Low-poly car. With ``name`` it becomes its own object (for animation/markers)."""
        mb = MeshBuilder(name) if name else self.mb
        T = Matrix.Translation((x, y, 0)) @ Matrix.Rotation(math.radians(yaw), 4, "Z")
        paint = self.m("car_%d%d%d" % tuple(int(c * 9) for c in color), color, roughness=0.25, coat=0.8)
        glass = self.m("glass", (0.3, 0.45, 0.6), roughness=0.05, metallic=0.4)
        tyre = self.m("tyre", (0.06, 0.06, 0.07), roughness=0.8)
        rim = self.m("rim", (0.75, 0.75, 0.78), metallic=0.9, roughness=0.3)
        mb.box(None, None, paint, matrix=T @ Matrix.Translation((0, 0, 0.62)) @ Matrix.Diagonal((3.8, 1.7, 0.6, 1)))
        mb.box(None, None, paint, matrix=T @ Matrix.Translation((0.1, 0, 1.15)) @ Matrix.Diagonal((2.0, 1.5, 0.55, 1)))
        mb.box(None, None, glass, matrix=T @ Matrix.Translation((0.1, 0, 1.15)) @ Matrix.Diagonal((2.05, 1.42, 0.42, 1)))
        for wx in (-1.25, 1.25):
            for wy in (-0.82, 0.82):
                wm = T @ Matrix.Translation((wx, wy, 0.38)) @ Matrix.Rotation(math.pi / 2, 4, "X")
                mb.cylinder(None, 0.38, 0.28, tyre, segs=16, matrix=wm)
                mb.cylinder(None, 0.2, 0.3, rim, segs=10, matrix=wm)
        for wx in (-1.92,):
            for wy in (-0.6, 0.6):
                mb.sphere(None, None, self.m("headlight", (1, 0.95, 0.7), emission=1.0), segs=8, rings=6,
                          matrix=T @ Matrix.Translation((wx, wy, 0.72)) @ Matrix.Diagonal((0.05, 0.16, 0.1, 1)))
        if name:
            obj = mb.to_object(self.coll)
            self.dynamic.append(obj)
            return obj
        return None

    def motorcycle(self, name: str, x: float = 0.0, y: float = 0.0, color=(0.1, 0.35, 0.85)):
        """Motorcycle as its own object; origin on the ground under the seat, facing -Y."""
        mb = MeshBuilder(name)
        paint = self.m("bike_paint", color, roughness=0.2, coat=0.8)
        tyre = self.m("tyre", (0.06, 0.06, 0.07), roughness=0.8)
        chrome = self.m("chrome", (0.8, 0.82, 0.85), metallic=0.95, roughness=0.15)
        seat = self.m("seat", (0.08, 0.08, 0.08), roughness=0.6)
        for wy in (-0.72, 0.72):
            wm = Matrix.Translation((0, wy, 0.33)) @ Matrix.Rotation(math.pi / 2, 4, "Y")
            mb.torus(None, 0.27, 0.07, tyre, segs=20, ring_segs=8, matrix=wm)
            mb.cylinder(None, 0.08, 0.12, chrome, segs=10, matrix=wm)
        mb.capsule((0, 0.55, 0.45), (0, -0.4, 0.62), 0.09, 0.09, paint, segs=10)
        mb.sphere((0, -0.15, 0.68), (0.2, 0.32, 0.15), paint, segs=14, rings=8)  # tank
        mb.box((0, 0.3, 0.74), (0.24, 0.55, 0.08), seat)
        mb.capsule((0, -0.62, 0.35), (0, -0.48, 0.95), 0.035, 0.035, chrome, segs=8)  # fork
        mb.capsule((-0.33, -0.48, 0.97), (0.33, -0.48, 0.97), 0.025, 0.025, chrome, segs=8)  # handlebar
        mb.sphere((0, -0.62, 0.86), (0.1, 0.06, 0.1), self.m("headlight", (1, 0.95, 0.7), emission=1.0), segs=10,
                  rings=6)
        mb.capsule((0.15, 0.5, 0.3), (0.15, 0.95, 0.4), 0.04, 0.05, chrome, segs=8)  # exhaust
        obj = mb.to_object(self.coll)
        obj.location = (x, y, 0)
        self.dynamic.append(obj)
        return obj

    def crane(self, x: float, y: float) -> None:
        yel = self.m("crane", (0.98, 0.72, 0.08), roughness=0.5)
        for k in range(10):
            z = k * 1.0
            self.mb.box((x, y, z + 0.5), (0.6, 0.6, 1.0), yel)
            self.mb.box((x, y, z + 0.5), (0.7, 0.1, 0.05), self.m("crane_dark", (0.2, 0.2, 0.2)))
        self.mb.box((x - 2.5, y, 10.2), (9.0, 0.5, 0.45), yel)
        self.mb.box((x + 1.5, y, 9.7), (1.2, 1.0, 0.8), self.m("crane_dark", (0.2, 0.2, 0.2)))
        self.mb.capsule((x - 5.5, y, 10.0), (x - 5.5, y, 6.2), 0.02, 0.02, self.m("cable", (0.1, 0.1, 0.1)), segs=6,
                        caps=False)
        self.mb.box((x - 5.5, y, 6.0), (0.5, 0.5, 0.3), self.m("crane_dark", (0.2, 0.2, 0.2)))

    def bricks(self, x: float, y: float, rows: int = 4) -> None:
        mat = self.m("brick", (0.72, 0.3, 0.2), roughness=0.9)
        for r_ in range(rows):
            for c_ in range(4):
                off = 0.12 if r_ % 2 else 0
                self.mb.box((x + c_ * 0.26 + off, y, 0.06 + r_ * 0.13), (0.24, 0.12, 0.11), mat)

    def wall_in_progress(self, x: float, y: float, length: float = 5.0, height: float = 1.4) -> None:
        mat = self.m("brick", (0.72, 0.3, 0.2), roughness=0.9)
        rows = int(height / 0.2)
        for r_ in range(rows):
            n = int(length / 0.42) - (r_ // 2)
            off = 0.21 if r_ % 2 else 0
            for c_ in range(max(1, n)):
                self.mb.box((x - length / 2 + off + c_ * 0.42, y, 0.1 + r_ * 0.2), (0.4, 0.2, 0.18), mat)

    def cement_bags(self, x: float, y: float) -> None:
        mat = self.m("bag", (0.85, 0.82, 0.72), roughness=0.95)
        for i in range(5):
            self.mb.sphere((x + (i % 3) * 0.55, y + (i // 3) * 0.1, 0.12 + (i // 3) * 0.2), (0.27, 0.18, 0.11), mat,
                           segs=10, rings=6)

    def barrier(self, x: float, y: float, length: float = 2.0) -> None:
        self.mb.box((x, y, 0.5), (length, 0.12, 0.25), self.m("barrier_red", (0.9, 0.2, 0.15)))
        for k in range(int(length / 0.5)):
            self.mb.box((x - length / 2 + 0.25 + k * 0.5, y - 0.07, 0.5), (0.18, 0.02, 0.26),
                        self.m("barrier_white", (0.95, 0.95, 0.95)))
        for dx in (-length / 2 + 0.1, length / 2 - 0.1):
            self.mb.box((x + dx, y, 0.2), (0.08, 0.4, 0.4), self.m("barrier_leg", (0.3, 0.3, 0.3)))

    def scaffold(self, x: float, y: float, w: float, h: float) -> None:
        pipe = self.m("pipe", (0.6, 0.62, 0.66), metallic=0.8, roughness=0.35)
        for px in (x - w / 2, x + w / 2):
            for py in (y - 0.6, y + 0.6):
                self.mb.capsule((px, py, 0), (px, py, h), 0.04, 0.04, pipe, segs=6, caps=False)
        for z in range(1, int(h) + 1, 2):
            self.mb.box((x, y, z), (w, 1.3, 0.06), self.m("plank", (0.65, 0.48, 0.3)))

    def crate(self, x: float, y: float, s: float = 0.8, z: float = 0.0) -> None:
        self.mb.box((x, y, z + s / 2), (s, s, s), self.m("crate", (0.62, 0.45, 0.25), roughness=0.9))

    def barrel(self, x: float, y: float, color=(0.2, 0.45, 0.75)) -> None:
        self.mb.cylinder((x, y, 0.45), 0.3, 0.9, self.m("barrel_%d" % int(color[2] * 9), color, roughness=0.5), segs=14)

    def tyres(self, x: float, y: float, n: int = 3) -> None:
        tyre = self.m("tyre", (0.06, 0.06, 0.07), roughness=0.8)
        for i in range(n):
            self.mb.torus((x, y, 0.1 + i * 0.2), 0.3, 0.1, tyre, segs=16, ring_segs=6)

    def bench(self, x: float, y: float, yaw: float = 0) -> None:
        wood = self.m("bench_wood", (0.6, 0.38, 0.2))
        self.mb.box((x, y, 0.45), (1.6, 0.45, 0.07), wood)
        self.mb.box((x, y + 0.22, 0.75), (1.6, 0.06, 0.4), wood)
        for dx in (-0.7, 0.7):
            self.mb.box((x + dx, y, 0.22), (0.07, 0.4, 0.44), self.m("pole", (0.25, 0.27, 0.3)))

    def tool_rack(self, x: float, y: float) -> None:
        self.mb.box((x, y, 1.6), (2.4, 0.08, 1.4), self.m("pegboard", (0.75, 0.6, 0.4)))
        metal = self.m("tool_metal", (0.55, 0.57, 0.6), metallic=0.85, roughness=0.3)
        red = self.m("tool_red", (0.85, 0.15, 0.12))
        for i in range(7):
            tx = x - 1.0 + i * 0.33
            self.mb.box((tx, y - 0.07, 1.6 + (0.25 if i % 2 else -0.15)), (0.05, 0.04, 0.5), metal)
            self.mb.box((tx, y - 0.08, 1.85 + (0.25 if i % 2 else -0.15)), (0.14, 0.05, 0.08), red if i % 3 else metal)

    def lift(self, x: float, y: float) -> None:
        post = self.m("lift_blue", (0.15, 0.35, 0.75), metallic=0.4, roughness=0.4)
        for dx in (-1.6, 1.6):
            self.mb.box((x + dx, y, 1.3), (0.3, 0.3, 2.6), post)
        self.mb.box((x, y, 0.9), (3.0, 0.18, 0.1), self.m("tool_metal", (0.55, 0.57, 0.6), metallic=0.85))

    def ground(self, color, size=(90, 70)) -> None:
        self.mb.box((0, 10, -0.05), (size[0], size[1], 0.1), self.m("ground_" + self.type, color, roughness=0.95))

    def road(self, y: float = 0.0, width: float = 7.0) -> None:
        self.mb.box((0, y, 0.005), (90, width, 0.02), self.m("asphalt", (0.22, 0.22, 0.25), roughness=0.9))
        for k in range(-20, 21):
            self.mb.box((k * 2.4, y, 0.02), (1.2, 0.14, 0.02), self.m("road_line", (0.98, 0.95, 0.85)))
        for side in (-1, 1):
            self.mb.box((0, y + side * (width / 2 + 0.6), 0.08), (90, 1.2, 0.16),
                        self.m("sidewalk", (0.72, 0.72, 0.7), roughness=0.9))

    # ------------------------------------------------------------- dressing
    def sky_and_light(self) -> None:
        st = self.style
        scene = bpy.context.scene
        world = bpy.data.worlds.new(f"world_{self.type}")
        world.use_nodes = True
        bg = world.node_tree.nodes["Background"]
        bg.inputs[0].default_value = (*srgb_to_linear([c * 0.9 for c in st["zenith"]]), 1)
        bg.inputs[1].default_value = 0.4 if st.get("interior") else 0.9
        scene.world = world
        if not st.get("interior"):
            dome_mb = MeshBuilder("sky_dome")
            dome_mb.sphere((0, 0, 0), (120, 120, 60), gradient_sky_material(f"sky_{self.type}", st["horizon"],
                                                                             st["zenith"]), segs=32, rings=16)
            dome = dome_mb.to_object(self.coll)
            dome.visible_shadow = False
            cloud_mb = MeshBuilder("clouds")
            cmat = material("env_cloud", (1, 1, 1), emission=0.6, roughness=1.0)
            for i in range(9):
                cx = self.rng.uniform(-60, 60)
                cy = self.rng.uniform(45, 75)
                cz = self.rng.uniform(14, 26)
                for k in range(4):
                    cloud_mb.sphere((cx + k * 2.2, cy, cz + (k % 2) * 0.8), (2.6, 1.6, 1.4), cmat, segs=10, rings=6)
            clouds = cloud_mb.to_object(self.coll)
            clouds.visible_shadow = False
        # Animated-feature lighting: warm low key sun, cool sky fill, back rim light.
        sun_d = bpy.data.lights.new("sun", "SUN")
        sun_d.energy = 2.4 if st.get("interior") else 4.2
        warm = st["sun_color"]
        sun_d.color = (warm[0], warm[1] * 0.9, warm[2] * 0.75)
        sun_d.angle = math.radians(3.0)
        sun = bpy.data.objects.new("sun", sun_d)
        elev, az = st["sun"]
        sun.rotation_euler = (math.radians(90 - min(elev, 42)), 0, math.radians(az))
        self.coll.objects.link(sun)
        rim_d = bpy.data.lights.new("rim", "SUN")
        rim_d.energy = 1.6
        rim_d.color = (0.75, 0.85, 1.0)
        rim_d.use_shadow = False
        rim = bpy.data.objects.new("rim", rim_d)
        rim.rotation_euler = (math.radians(-60), 0, math.radians(200))  # from behind the characters
        self.coll.objects.link(rim)
        fill_d = bpy.data.lights.new("fill", "AREA")
        fill_d.energy = 700
        fill_d.size = 12
        fill_d.color = (0.8, 0.88, 1.0)
        fill_d.use_shadow = False  # large shadowed area lights are the main source of EEVEE grain
        fill = bpy.data.objects.new("fill", fill_d)
        fill.location = (0, -12, 7)
        fill.rotation_euler = (math.radians(60), 0, 0)
        self.coll.objects.link(fill)

    # ------------------------------------------------------- environments
    def build(self) -> dict:
        st = self.style
        if self.backdrop and not st.get("interior"):
            # ground stops where the painted backdrop starts, so its painted ground continues it
            self.mb.box((0, 2.0, -0.05), (90, 54, 0.1), self.m("ground_" + self.type, st["ground"], roughness=0.95))
        else:
            self.ground(st["ground"])
        getattr(self, f"_env_{self.type}")()
        self.sky_and_light()
        if self.backdrop:
            self._painted_backdrop()
        self.mb.to_object(self.coll)
        return {"markers": self.markers, "dynamic": [o.name for o in self.dynamic]}

    def _painted_backdrop(self) -> None:
        """AI-painted background on a huge plane behind the set (emission: unaffected by scene lights).

        Placed so the painting's horizon (~45 % up) sits at camera eye height; the 3D ground hides
        the part below ground level, so the painted ground continues the real one."""
        img = bpy.data.images.load(self.backdrop)
        img.pack()  # keep the .blend self-contained
        mat = bpy.data.materials.new("env_painted_backdrop")
        mat.use_nodes = True
        nt = mat.node_tree
        nt.nodes.clear()
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        em = nt.nodes.new("ShaderNodeEmission")
        em.inputs["Strength"].default_value = 0.95
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = img
        tex.extension = "EXTEND"
        nt.links.new(tex.outputs["Color"], em.inputs["Color"])
        nt.links.new(em.outputs[0], out.inputs[0])
        w, h = 72.0, 40.5
        depth = 29.0 if not self.style.get("interior") else 5.6
        bottom = 2.0 - 0.45 * h
        mesh = bpy.data.meshes.new("painted_backdrop")
        cols = 24
        verts, faces = [], []
        for i in range(cols + 1):
            u = i / cols
            x = (u - 0.5) * w
            y = depth + 0.004 * x * x  # gentle curve so pans and orbits stay inside the painting
            verts += [(x, y, bottom), (x, y, bottom + h)]
        for i in range(cols):
            a = 2 * i
            faces.append((a, a + 2, a + 3, a + 1))
        mesh.from_pydata(verts, [], faces)
        uv = mesh.uv_layers.new(name="UVMap")
        for poly in mesh.polygons:
            for li in poly.loop_indices:
                vi = mesh.loops[li].vertex_index
                uv.data[li].uv = ((vi // 2) / cols, vi % 2)
        mesh.materials.append(mat)
        obj = bpy.data.objects.new("painted_backdrop", mesh)
        obj.visible_shadow = False
        self.coll.objects.link(obj)
        for o in list(self.coll.objects):  # the painting replaces the procedural sky dome and clouds
            if o.name.startswith(("sky_dome", "clouds")):
                bpy.data.objects.remove(o, do_unlink=True)

    def _city_backdrop(self, y: float = 9.0, count: int = 7) -> None:
        if self.backdrop:
            return  # the painted background already shows the city
        x = -24.0
        while x < 24:
            w = self.rng.uniform(4, 7)
            self.building(x + w / 2, y + self.rng.uniform(0, 3), w, 4, self.rng.uniform(5, 13))
            x += w + self.rng.uniform(0.3, 1.2)

    def _env_construction_site(self) -> None:
        self._city_backdrop(y=16)
        self.scaffold(-2.5, 6.5, 6, 6)
        self.building(-2.5, 7.5, 6, 2.5, 4.5, color=(0.75, 0.73, 0.7), windows=False)
        self.crane(8, 9)
        self.wall_in_progress(-4.8, 3.6, length=4.0, height=1.2)
        self.bricks(3.8, 3.4)
        self.bricks(5.0, 4.2, rows=5)
        self.cement_bags(-8.5, 1.5)
        self.cement_bags(8.2, 2.5)
        self.barrier(-9.5, -2.0, 2.5)
        self.barrier(9.5, -2.0, 2.5)
        self.mb.cylinder((7.6, 0.8, 0.45), 0.5, 0.9, self.m("mixer", (0.95, 0.55, 0.1)), segs=14)
        self.markers["work_spot"] = (-3.5, 2.6, 0)

    def _env_city_road(self) -> None:
        self.road(y=0.0, width=7.0)
        self._city_backdrop(y=9)
        for x in (-12, -6, 6, 12):
            self.streetlight(x, 4.4)
        for x in (-15, -9, 9, 15):
            self.tree(x, 5.5, 1.1)
        self.car(-13, 2.0, (0.2, 0.6, 0.3), yaw=90)
        self.car(14, 2.0, (0.95, 0.75, 0.1), yaw=90)

    def _env_motorcycle_garage(self) -> None:
        self.building(0, 7.5, 16, 4, 5.5, color=(0.85, 0.8, 0.7), windows=False, sign="BIKE GARAGE")
        self.box((-3, 5.45, 1.6), (4.0, 0.1, 3.2), "garage_door", (0.6, 0.62, 0.66), metallic=0.5)
        for k in range(8):
            self.box((-3, 5.38, 0.2 + k * 0.4), (4.0, 0.02, 0.05), "garage_line", (0.45, 0.47, 0.5))
        self.tyres(5.5, 4.0, 4)
        self.tyres(6.4, 4.2, 3)
        self.tool_rack(3, 5.4)
        self.motorcycle("parked_bike", 7.5, 1.5, color=(0.85, 0.15, 0.1)).rotation_euler.z = math.radians(70)
        self._city_backdrop(y=18)

    def _env_car_workshop(self) -> None:
        self.building(0, 8, 18, 5, 6, color=(0.78, 0.82, 0.86), windows=False, sign="WORKSHOP")
        self.box((0, 5.48, 2.2), (9, 0.1, 4.4), "shop_dark", (0.18, 0.2, 0.24))
        self.lift(-4.5, 4.4)
        car = self.car(-4.5, 4.4, (0.15, 0.4, 0.85), yaw=0, name="repair_car")
        car.location.z = 0.0
        self.tool_rack(3.5, 5.3)
        self.tyres(7.2, 3.6, 4)
        self.barrel(-8.0, 3.2, (0.85, 0.2, 0.15))
        self.barrel(-7.3, 3.8, (0.2, 0.45, 0.75))
        self.box((5.8, 3.4, 0.45), (1.8, 0.8, 0.9), "workbench", (0.5, 0.35, 0.2))
        self.markers["work_spot"] = (-2.6, 2.6, 0)
        self._city_backdrop(y=20)

    def _env_house(self) -> None:
        self.building(-1, 7, 9, 5, 4.2, color=(0.95, 0.88, 0.7), roof="gable")
        self.box((-1, 4.45, 1.1), (1.2, 0.1, 2.2), "door", (0.5, 0.28, 0.15))
        for x in (-12, -8, 7, 11):
            self.tree(x, 6, 1.2)
        for k in range(-10, 11):
            self.box((k * 1.0, 3.2, 0.45), (0.12, 0.08, 0.9), "fence", (0.98, 0.98, 0.95))
        self.box((0, 3.2, 0.75), (21, 0.06, 0.1), "fence", (0.98, 0.98, 0.95))

    def _env_school(self) -> None:
        self.building(0, 9, 20, 5, 7.5, color=(0.95, 0.85, 0.6), sign="SCHOOL")
        self.mb.capsule((-8, 4.5, 0), (-8, 4.5, 6), 0.06, 0.05, self.m("pole", (0.25, 0.27, 0.3)), segs=8)
        self.box((-7.4, 4.5, 5.4), (1.2, 0.04, 0.8), "flag", (0.05, 0.45, 0.2))
        for x in (-12, 10, 13):
            self.tree(x, 5, 1.1)
        self.bench(5, 3.8)

    def _env_police_station(self) -> None:
        self.building(0, 8.5, 16, 5, 6.5, color=(0.82, 0.86, 0.92), sign="POLICE")
        self.box((0, 5.95, 1.2), (2.4, 0.1, 2.4), "door_blue", (0.12, 0.25, 0.55))
        self.car(8.5, 3.0, (0.95, 0.95, 0.97), yaw=90, name="police_car")
        self.mb.box((8.5, 3.0, 1.5), (0.25, 0.9, 0.12), self.m("siren_light", (0.2, 0.3, 1.0), emission=3.0))
        self.streetlight(-8, 4.5)
        self.road(y=-6.5, width=4.0)

    def _env_park(self) -> None:
        for x, y, s in ((-12, 6, 1.3), (-7, 9, 1.0), (-3, 12, 1.4), (4, 10, 1.1), (9, 7, 1.3), (13, 11, 1.2),
                        (-15, 12, 1.2), (16, 6, 1.0)):
            self.tree(x, y, s)
        self.bench(-6, 4.0)
        self.bench(6, 4.0)
        frame = self.m("swing", (0.9, 0.35, 0.2))
        for dx in (-1.2, 1.2):
            self.mb.capsule((10 + dx, 4.5, 0), (10 + dx, 4.5, 2.4), 0.06, 0.06, frame, segs=8, caps=False)
        self.mb.capsule((8.8, 4.5, 2.4), (11.2, 4.5, 2.4), 0.06, 0.06, frame, segs=8)
        self.box((-11, 4.2, 1.0), (0.8, 3.0, 0.08), "slide", (0.95, 0.8, 0.1))
        flowers = [self.m("flower_" + n, c, emission=0.1) for n, c in
                   (("r", (0.95, 0.25, 0.3)), ("y", (1, 0.85, 0.2)), ("p", (0.75, 0.4, 0.9)))]
        for i in range(40):
            x = self.rng.uniform(-14, 14)
            y = self.rng.uniform(3.2, 8)
            self.mb.sphere((x, y, 0.12), (0.12, 0.12, 0.1), flowers[i % 3], segs=8, rings=5)
        self._city_backdrop(y=24)

    def _env_hideout(self) -> None:
        wall = self.m("hideout_wall", (0.35, 0.3, 0.38), roughness=0.95)
        self.mb.box((0, 6, 3.5), (26, 0.4, 7), wall)
        for sx in (-1, 1):
            self.mb.box((sx * 11, 0, 3.5), (0.4, 14, 7), wall)
        self.mb.box((0, 0, 7.1), (26, 14, 0.3), wall)
        for x, y in ((-7, 4), (-6.2, 4.2), (-6.6, 3.6), (6.5, 4.5), (7.3, 4.0)):
            self.crate(x, y)
        self.crate(-6.6, 4.0, 0.7, 0.8)
        for x in (-8.5, 8.6, 9.2):
            self.barrel(x, 2.5, (0.5, 0.15, 0.6))
        self.text("BOSS HQ", (0, 5.75, 4.2), size=0.9, color=(0.7, 0.3, 0.95))
        for x in (-4, 4):
            d = bpy.data.lights.new(f"lamp_{x}", "POINT")
            d.energy = 1600
            d.color = (1.0, 0.8, 0.55)
            d.shadow_soft_size = 0.4
            lo = bpy.data.objects.new(f"lamp_{x}", d)
            lo.location = (x, 0.5, 5.5)
            self.coll.objects.link(lo)
            self.mb.capsule((x, 0.5, 7), (x, 0.5, 5.8), 0.02, 0.02, self.m("cable", (0.1, 0.1, 0.1)), segs=6)
            self.mb.sphere((x, 0.5, 5.7), (0.3, 0.3, 0.2), self.m("lamp", (1, 0.95, 0.75), emission=2.0))

    def mud_house(self, x: float, y: float, w: float, d: float, h: float) -> None:
        mud = self.m("mud_wall", (0.82, 0.66, 0.47), roughness=0.95)
        dark = self.m("mud_dark", (0.66, 0.5, 0.35), roughness=0.95)
        self.mb.box((x, y, h / 2), (w, d, h), mud)
        self.mb.box((x, y, h + 0.12), (w + 0.15, d + 0.15, 0.24), dark)          # parapet
        for k in range(int(w // 1.2)):                                            # roof beams
            self.mb.cylinder(None, 0.07, d + 0.6, self.m("beam", (0.45, 0.3, 0.18)), segs=8,
                             matrix=Matrix.Translation((x - w / 2 + 0.6 + k * 1.2, y - 0.3, h - 0.25))
                             @ Matrix.Rotation(math.pi / 2, 4, "X"))
        self.mb.box((x - w * 0.18, y - d / 2 - 0.03, 1.05), (1.0, 0.08, 2.1), self.m("wood_door", (0.42, 0.25, 0.13)))
        self.mb.box((x + w * 0.25, y - d / 2 - 0.03, 1.6), (0.6, 0.06, 0.55), self.m("window_dark", (0.15, 0.1, 0.08)))

    def charpai(self, x: float, y: float, yaw: float = 0.0) -> None:
        wood = self.m("charpai_wood", (0.55, 0.36, 0.2), roughness=0.7)
        weave = self.m("charpai_rope", (0.85, 0.72, 0.5), roughness=0.95)
        T = Matrix.Translation((x, y, 0)) @ Matrix.Rotation(math.radians(yaw), 4, "Z")
        for dx in (-0.95, 0.95):
            for dy in (-0.45, 0.45):
                self.mb.cylinder(None, 0.05, 0.5, wood, segs=8, matrix=T @ Matrix.Translation((dx, dy, 0.25)))
        self.mb.box(None, None, weave, matrix=T @ Matrix.Translation((0, 0, 0.48)) @ Matrix.Diagonal((1.95, 0.95, 0.04, 1)))
        for dy in (-0.47, 0.47):
            self.mb.box(None, None, wood, matrix=T @ Matrix.Translation((0, dy, 0.5)) @ Matrix.Diagonal((2.05, 0.07, 0.07, 1)))

    def matka(self, x: float, y: float, s: float = 1.0) -> None:
        clay = self.m("clay", (0.78, 0.42, 0.25), roughness=0.6)
        self.mb.sphere((x, y, 0.32 * s), (0.32 * s, 0.32 * s, 0.3 * s), clay, segs=18, rings=12)
        self.mb.cylinder((x, y, 0.62 * s), 0.12 * s, 0.12 * s, clay, segs=14, radius2=0.15 * s)

    def _env_village(self) -> None:
        for x, y, w, h in ((-9.5, 6.5, 6.5, 3.2), (-2.0, 8.0, 7.0, 3.6), (6.0, 6.8, 6.0, 3.0), (13, 9, 6, 3.4),
                           (-16, 9, 6, 3.0)):
            self.mud_house(x, y, w, 4.0, h)
        self.mb.box((0, 4.2, 0.6), (30, 0.35, 1.2), self.m("mud_wall", (0.82, 0.66, 0.47), roughness=0.95))
        for x, y, s_ in ((-12.5, 4.0, 1.5), (10.5, 3.6, 1.4), (17, 5, 1.3)):
            self.tree(x, y, s_)
        self.charpai(-5.0, 2.6, yaw=8)
        self.charpai(5.5, 3.0, yaw=-12)
        for x, y, s_ in ((-7.3, 3.4, 1.0), (-6.7, 3.7, 0.8), (7.6, 3.5, 1.1), (8.2, 3.2, 0.75)):
            self.matka(x, y, s_)
        hay = self.m("hay", (0.9, 0.78, 0.4), roughness=1.0)
        self.mb.cylinder((-9.5, 2.6, 0.7), 0.9, 1.4, hay, segs=18, radius2=0.25)
        self.markers["work_spot"] = (-4.0, 2.2, 0)

    def _env_shop(self) -> None:
        for i, x in enumerate((-8, 0, 8)):
            self.building(x, 7, 7.5, 4, 5, sign=("SHOP", "BAZAAR", "STORE")[i])
            for k in range(6):
                self.box((x - 3 + k * 1.2, 4.6, 3.0), (1.2, 1.2, 0.08), "awning_%d" % (k % 2),
                         (0.9, 0.2, 0.2) if k % 2 else (0.98, 0.98, 0.95))
        for x in (-5, 4.5):
            self.crate(x, 3.6, 0.6)
        self._city_backdrop(y=18)


def build_environment(env_type: str, collection, seed: int = 1) -> dict:
    return EnvironmentBuilder(env_type, collection, seed).build()
