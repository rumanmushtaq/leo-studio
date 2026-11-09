"""Procedural stylised 3D cartoon characters (run inside Blender).

A character = armature (``rig_builder``) + skinned body mesh with toon outline
+ face mesh carrying facial shape keys (Blink, Open, Wide, Round, Smile, Frown)
+ optional cape mesh. Everything lives in collection ``CHR_<id>`` and is saved
to ``assets/characters/<id>.blend`` so each scene appends the same asset.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

from blender import base_body
from blender.material_builder import embroidered_material, material, outline_material
from blender.mesh_utils import MeshBuilder, frame_matrix
from blender.motion_math import smoothstep
from blender.rig_builder import build_rig, compute_dims

SHAPE_KEYS = ["Blink", "Open", "Wide", "Round", "Smile", "Frown", "MBP", "FV"]


def _c(v, default=(0.5, 0.5, 0.5)):
    return tuple(v) if v else default


class CharacterBuilder:
    def __init__(self, cid: str, spec: dict):
        self.cid = cid
        self.spec = spec
        self.d = compute_dims(spec)
        cos = spec.get("costume", {})
        p = cid + "_"
        self.m = {
            "skin": material(p + "skin", _c(spec.get("skin")), roughness=0.55, specular=0.3, subsurface=0.15),
            "blush": material(p + "blush", tuple(min(1.0, c * k) for c, k in zip(_c(spec.get("skin")), (1.04, 0.86, 0.84))),
                              roughness=0.6, specular=0.25),
            "skin_dark": material(p + "skin_dark", tuple(c * 0.85 for c in _c(spec.get("skin"))), roughness=0.6),
            "hair": material(p + "hair", _c(spec.get("hair", {}).get("color")), roughness=0.45, specular=0.5),
            "shirt": material(p + "shirt", _c(cos.get("shirt")), roughness=0.5),
            "sleeves": material(p + "sleeves", _c(cos.get("sleeves") or cos.get("shirt"))),
            "pants": material(p + "pants", _c(cos.get("pants")), roughness=0.6),
            "shoes": material(p + "shoes", _c(cos.get("shoes")), roughness=0.35, coat=0.3),
            "gloves": material(p + "gloves", _c(cos.get("gloves"), _c(spec.get("skin"))), roughness=0.5),
            "belt": material(p + "belt", _c(cos.get("belt"), (0.1, 0.1, 0.1)), roughness=0.35, metallic=0.2),
            "eye_white": material(p + "eye_white", (0.97, 0.97, 0.97), roughness=0.15, specular=0.6),
            "iris": material(p + "iris", tuple(min(1.0, c * 1.35 + 0.05) for c in _c(spec.get("eye_color"))),
                             roughness=0.15, specular=0.7, coat=0.8),
            "iris_rim": material(p + "iris_rim", tuple(c * 0.45 for c in _c(spec.get("eye_color"))), roughness=0.2),
            "pupil": material(p + "pupil", (0.02, 0.02, 0.025), roughness=0.1),
            "highlight": material(p + "highlight", (1, 1, 1), emission=1.2),
            "mouth": material(p + "mouth", (0.42, 0.06, 0.08), roughness=0.5),
            "gold": material(p + "gold", (1.0, 0.72, 0.12), roughness=0.25, metallic=0.85),
            "metal": material(p + "metal", (0.62, 0.64, 0.68), roughness=0.3, metallic=0.9),
            "cape": material(p + "cape", _c(spec.get("cape_color"), (0.1, 0.3, 0.85)), roughness=0.5),
            "helmet": material(p + "helmet", _c(spec.get("helmet_color"), (0.98, 0.82, 0.1)), roughness=0.25,
                               coat=0.6),
            "visor": material(p + "visor", (0.05, 0.08, 0.12), roughness=0.05, metallic=0.4, coat=1.0),
            "vest": material(p + "vest", _c(spec.get("vest_color"), (1.0, 0.45, 0.05)), roughness=0.5),
            "stripe": material(p + "stripe", (0.85, 0.87, 0.85), roughness=0.2, metallic=0.6),
            "jacket": material(p + "jacket", _c(spec.get("jacket_color"), _c(cos.get("shirt"))), roughness=0.4),
            "red": material(p + "red", (0.85, 0.1, 0.12), roughness=0.4),
            "sole": material(p + "sole", (0.25, 0.16, 0.1), roughness=0.7),
            "waistcoat": embroidered_material(p + "waistcoat", _c(spec.get("waistcoat_color"), (0.7, 0.1, 0.1)),
                                              (0.95, 0.75, 0.25)),
        }
        self.outline = outline_material()

    # ------------------------------------------------------------------ build
    def build(self, collection) -> bpy.types.Object:
        acc = set(self.spec.get("accessories", []))
        gender = "female" if self.spec.get("gender") == "female" else "male"
        imported = bool(self.spec.get("model_file"))
        keep_head = imported and bool(self.spec.get("keep_head"))
        use_base = imported or (base_body.available(gender) and not self.spec.get("procedural_body"))
        if use_base:
            # imported user model, or the CC0 Quaternius base body; re-proportioned and re-skinned to our rig
            skin_obj, joints = base_body.build_base_body(self.cid, self.spec, self.d, collection)
            self.d = base_body.dims_from_joints(self.d, joints, skin_obj)
        rig = build_rig(f"{self.cid}_rig", self.d, collection, cape="cape" in acc)
        rig["char_id"] = self.cid
        rig["dims"] = json.dumps(self.d)
        rig["spec"] = json.dumps(self.spec, ensure_ascii=False)
        rig["body_source"] = ("imported:" + Path(self.spec["model_file"]).name if imported else
                              "quaternius_ubc_cc0" if use_base else "procedural_metaball")
        self.rig = rig

        if use_base:
            base_body.remap_groups(skin_obj)
            if not keep_head:
                base_body.remove_head(skin_obj, self.d["neck_top"])
            skin_obj.parent = rig
            if not imported or self.spec.get("recolor"):
                bones = {b.name: (Vector(b.head_local), Vector(b.tail_local)) for b in rig.data.bones}
                skin_obj.data.materials.clear()
                self._weight_and_paint(skin_obj, bones, acc, assign_weights=False)
        else:
            skin_obj = self._smooth_body(collection, acc)
        if "waistcoat" in acc:
            self._waistcoat_shell(skin_obj)
        self._skin(skin_obj)
        self._outline(skin_obj, 0.0045)

        body = MeshBuilder(f"{self.cid}_body")
        self._body(body, acc)
        if not keep_head:
            self._head(body, acc)
        if body.bm.verts:
            body_obj = body.to_object(collection, parent=rig)
            self._skin(body_obj)
            self._outline(body_obj, 0.004)
        else:
            body.bm.free()

        if keep_head:
            # the imported face drives lip-sync only if it carries compatible shape keys
            found = self._adopt_face_keys(skin_obj)
            skin_obj.name = f"{self.cid}_face"  # the animation baker looks for <id>_face
            rig["face_keys"] = json.dumps(found)
        else:
            face = MeshBuilder(f"{self.cid}_face")
            shapes = self._face(face)
            face_obj = face.to_object(collection, parent=rig)
            self._skin(face_obj)
            self._shape_keys(face_obj, shapes)

        if "cape" in acc:
            cape = MeshBuilder(f"{self.cid}_cape")
            self._cape(cape)
            cape_obj = cape.to_object(collection, parent=rig)
            self._skin(cape_obj)
        return rig

    # Common facial shape-key names (ARKit, Oculus visemes, Mixamo/Fuse, Blender) -> our keys
    FACE_KEY_ALIASES = {
        "Open": ["jawOpen", "mouthOpen", "viseme_aa", "MouthOpen", "A", "aa"],
        "Wide": ["mouthStretchLeft", "viseme_I", "viseme_E", "Mouth_Wide", "E", "ee"],
        "Round": ["mouthPucker", "mouthFunnel", "viseme_O", "viseme_U", "O", "oh", "ou"],
        "Smile": ["mouthSmile", "mouthSmileLeft", "Smile", "smile", "Mouth_Smile"],
        "Frown": ["mouthFrownLeft", "mouthFrown", "Frown", "frown"],
        "Blink": ["eyesClosed", "eyeBlinkLeft", "Blink", "blink", "Eye_Blink", "EyeBlink"],
    }

    def _adopt_face_keys(self, obj) -> dict:
        """Rename an imported model's facial shape keys to ours; return the mapping found."""
        keys = obj.data.shape_keys
        found = {}
        if not keys:
            return found
        names = {k.name: k for k in keys.key_blocks}
        for ours, aliases in self.FACE_KEY_ALIASES.items():
            if ours in names:
                found[ours] = ours
                continue
            for a in aliases:
                if a in names:
                    names[a].name = ours
                    found[ours] = a
                    break
        return found

    def _outline(self, obj, k: float) -> None:
        """Inverted-hull toon outline (last material slot, back faces culled)."""
        obj.data.materials.append(self.outline)
        sol = obj.modifiers.new("Outline", "SOLIDIFY")
        sol.thickness = k * self.d["H"]
        sol.offset = 1.0
        sol.use_flip_normals = True
        sol.use_rim = False
        sol.material_offset = len(obj.data.materials) - 1
        sol.material_offset_rim = len(obj.data.materials) - 1

    # ------------------------------------------------------------ smooth body
    def _smooth_body(self, collection, acc: set):
        """One continuous organic body (torso, neck, arms, 4-finger hands, legs, shoes).

        Built from metaball ellipsoids and capsules whose fields blend into a
        single smooth "vinyl toy" surface (soft armpits, waist, knees), then
        converted to a mesh. Weights come from distance to the rig's bone
        segments with smooth blending at joints, so limbs bend without seams.
        """
        d, H = self.d, self.d["H"]
        cos = self.spec.get("costume", {})
        bones = {b.name: (Vector(b.head_local), Vector(b.tail_local)) for b in self.rig.data.bones}
        meta = bpy.data.metaballs.new(f"{self.cid}_meta")
        meta.threshold = 0.6
        meta.resolution = 0.02 * H
        meta.render_resolution = 0.008 * H
        K = 1.0 / 0.672  # surface of an isolated element sits at 0.672 x radius (stiffness 2, threshold 0.6)

        def ellipsoid(p, rx, ry, rz, stiff=2.0):
            e = meta.elements.new(type="ELLIPSOID")
            e.co = Vector(p)
            e.radius = K
            e.size_x, e.size_y, e.size_z = rx, ry, rz
            e.stiffness = stiff

        def capsule(a, b, r, stiff=2.0):
            a, b = Vector(a), Vector(b)
            e = meta.elements.new(type="CAPSULE")
            e.co = (a + b) / 2
            e.radius = r * K
            e.size_x = max((b - a).length / 2, 1e-4)
            e.rotation = Vector((1, 0, 0)).rotation_difference((b - a).normalized())
            e.stiffness = stiff

        def ball(p, r, stiff=2.0):
            e = meta.elements.new(type="BALL")
            e.co = Vector(p)
            e.radius = r * K
            e.stiffness = stiff

        hz, T = d["hip_z"], d["torso_len"]
        rx, ry, belly = d["torso_rx"], d["torso_ry"], d["belly"]
        # torso: pelvis, belly, chest blend into one rounded body
        ellipsoid((0, 0, hz + 0.01 * H), rx * 0.88, ry * 0.9, 0.075 * H, 1.6)
        ellipsoid((0, -belly * 0.05 * H, hz + 0.36 * T), rx * (0.84 + belly * 0.7), ry * (0.9 + belly * 1.3),
                  0.24 * T, 1.6)
        ellipsoid((0, 0, hz + 0.72 * T), rx * 0.98, ry * 0.95, 0.27 * T, 1.6)
        capsule((0, 0.004 * H, d["neck_base"] - 0.02 * H), (0, 0.004 * H, d["neck_top"] + 0.03 * H), 0.038 * H)
        for side, sx in (("L", 1), ("R", -1)):
            sh = bones[f"upper_arm_{side}"][0]
            el = bones[f"forearm_{side}"][0]
            wr = bones[f"hand_{side}"][0]
            hd = bones[f"hand_{side}"][1]
            ball(sh + Vector((-sx * 0.01 * H, 0, 0)), d["arm_r"] * 1.25, 1.5)
            capsule(sh, el, d["arm_r"] * 1.02)
            capsule(el, wr, d["arm_r"] * 0.86)
            hand_dir = (hd - wr).normalized()
            palm = wr + hand_dir * 0.03 * H
            ellipsoid(palm, d["hand_r"] * 0.55, d["hand_r"] * 0.78, d["hand_r"] * 0.7, 2.0)
            fr = 0.24 * d["hand_r"]
            for spread in (-1.0, 0.0, 1.0):  # three chubby cartoon fingers + thumb
                base = palm + hand_dir * 0.5 * d["hand_r"] + Vector((0, spread * 0.5 * d["hand_r"], 0))
                tip = base + (hand_dir + Vector((0, spread * 0.2, 0))).normalized() * 0.85 * d["hand_r"]
                capsule(base, tip, fr, 2.2)
            capsule(palm + Vector((0, -0.4 * d["hand_r"], 0)),
                    palm + hand_dir * 0.25 * d["hand_r"] + Vector((-sx * 0.1 * d["hand_r"], -1.05 * d["hand_r"], 0)),
                    fr * 1.05, 2.2)
            hip = bones[f"thigh_{side}"][0]
            kn = bones[f"shin_{side}"][0]
            an = bones[f"shin_{side}"][1]
            toe = bones[f"foot_{side}"][1]
            capsule(hip + Vector((0, 0, -0.02 * H)), kn, d["thigh_r"] * 1.02)
            capsule(kn, an + Vector((0, 0, 0.02 * H)), d["shin_r"] * 1.0)
            ball(kn.lerp(an, 0.35), d["shin_r"] * 1.08, 1.2)  # calf
            boots = cos.get("shoe_style") == "boots"
            if boots:
                capsule(an + Vector((0, 0, 0.0)), an + Vector((0, 0, 0.12 * H)), d["shin_r"] * 1.12, 1.4)
            heel = an + Vector((0, 0.01 * H, -0.015 * H))
            front = toe + Vector((0, 0.006 * H, -0.002 * H))
            ellipsoid(heel.lerp(front, 0.5), d["shin_r"] * 1.15, (front - heel).length * 0.55, 0.03 * H, 2.0)
        obj = bpy.data.objects.new(f"{self.cid}_meta", meta)
        collection.objects.link(obj)
        dg = bpy.context.evaluated_depsgraph_get()
        mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(dg))
        mesh.name = f"{self.cid}_skinbody"
        bpy.data.objects.remove(obj)
        bpy.data.metaballs.remove(meta)
        body = bpy.data.objects.new(f"{self.cid}_skinbody", mesh)
        collection.objects.link(body)
        for poly in mesh.polygons:
            poly.use_smooth = True
        body.parent = self.rig
        self._weight_and_paint(body, bones, acc)
        return body

    def _weight_and_paint(self, obj, bones: dict, acc: set, assign_weights: bool = True) -> None:
        d, H, m = self.d, self.d["H"], self.m
        cos = self.spec.get("costume", {})
        deform = ["hips", "spine", "chest", "neck", "shoulder_L", "shoulder_R", "upper_arm_L", "upper_arm_R",
                  "forearm_L", "forearm_R", "hand_L", "hand_R", "thigh_L", "thigh_R", "shin_L", "shin_R",
                  "foot_L", "foot_R"]
        parent = {b.name: (b.parent.name if b.parent else None) for b in self.rig.data.bones}

        def seg_dist(p: Vector, a: Vector, b: Vector) -> tuple[float, float]:
            ab = b - a
            t = max(0.0, min(1.0, (p - a).dot(ab) / max(ab.length_squared, 1e-12)))
            return (p - (a + ab * t)).length, t

        def weights(p: Vector) -> list[tuple[str, float]]:
            cands = []
            for name in deform:
                if name.endswith("_L") and p.x < -0.01 * H or name.endswith("_R") and p.x > 0.01 * H:
                    continue
                dist, _ = seg_dist(p, *bones[name])
                if name in ("hips", "spine", "chest"):
                    dist *= 0.55  # torso bones sit inside a wide volume
                cands.append((dist, name))
            cands.sort()
            (d1, b1), (d2, b2) = cands[0], cands[1]
            if parent.get(b1) == b2 or parent.get(b2) == b1:
                blend = 0.05 * H
                w2 = 0.5 * (1 - smoothstep((d2 - d1) / blend))
                return [(b1, 1 - w2), (b2, w2)]
            return [(b1, 1.0)]

        if assign_weights:
            groups = {n: obj.vertex_groups.new(name=n) for n in deform}
            for vtx in obj.data.vertices:
                for name, w in weights(vtx.co):
                    if w > 1e-3:
                        groups[name].add([vtx.index], w, "REPLACE")

        torso_mat = m["vest"] if "reflective_vest" in acc else m["jacket"] if "jacket" in acc else m["shirt"]
        long_sleeve = cos.get("sleeve_length", "long") == "long"
        boots = cos.get("shoe_style") == "boots"
        sandals = cos.get("shoe_style") == "sandals"
        kurta = bool(cos.get("kurta"))
        knee_z = (d["hip_z"] + d["ankle_z"]) / 2
        glove = m["gloves"] if cos.get("gloves") else m["skin"]
        belt_z = d["hip_z"] + 0.03 * H
        slots = [torso_mat, m["pants"], m["skin"], m["sleeves"], glove, m["shoes"]]
        for mat in slots:
            obj.data.materials.append(mat)

        def pick(c: Vector) -> int:
            b = weights(c)[0][0]
            if b in ("hips", "spine", "chest") or b.startswith("shoulder"):
                if c.z < belt_z:
                    return 1
                # clean, curved armhole: torso garment inside, sleeves outside
                cut = d["shoulder_w"] * (0.74 + 0.25 * max(0.0, (d["neck_base"] - c.z) / max(d["torso_len"], 1e-6)))
                return 3 if (abs(c.x) > cut and c.z > d["hip_z"] + 0.45 * d["torso_len"]) else 0
            if b == "neck":
                return 2 if c.z > d["neck_base"] - 0.005 * H else 0
            if b.startswith("upper_arm"):
                a, tail = bones[b]
                _, t = seg_dist(c, a, tail)
                return 3 if (long_sleeve or t < 0.55) else 2
            if b.startswith("forearm"):
                a, tail = bones[b]
                _, t = seg_dist(c, a, tail)
                return 3 if long_sleeve and t < 0.92 else 2 if not long_sleeve else 4 if cos.get("gloves") else 2
            if b.startswith("hand"):
                return 4
            if b.startswith("foot"):
                return 2 if sandals else 5
            if b.startswith("shin"):
                if sandals:
                    return 1
                return 5 if c.z < d["ankle_z"] + (0.13 if boots else 0.03) * H else 1
            if kurta and b.startswith("thigh") and c.z > knee_z + 0.02 * H:
                return 0
            return 1

        for poly in obj.data.polygons:
            poly.material_index = pick(poly.center)
        if cos.get("dress"):
            for poly in obj.data.polygons:
                if poly.material_index == 1 and poly.center.z > d["ankle_z"] + 0.25 * H:
                    poly.material_index = 0

    def _skin(self, obj) -> None:
        mod = obj.modifiers.new("Armature", "ARMATURE")
        mod.object = self.rig
        mod.use_vertex_groups = True

    # ------------------------------------------------------------------- body
    def _torso_weights(self, co: Vector) -> dict:
        d = self.d
        z0 = d["hip_z"]
        t = d["torso_len"]
        h_s = smoothstep((co.z - (z0 + 0.12 * t)) / (0.18 * t))
        s_c = smoothstep((co.z - (z0 + 0.45 * t)) / (0.2 * t))
        return {"hips": 1 - h_s, "spine": h_s * (1 - s_c), "chest": s_c}

    def _body(self, mb: MeshBuilder, acc: set) -> None:
        d, m, H = self.d, self.m, self.d["H"]
        cos = self.spec.get("costume", {})
        tw = self._torso_weights
        zc = d["hip_z"] + d["torso_len"] * 0.5
        if cos.get("dress"):
            mb.cylinder((0, 0, d["hip_z"] - 0.1 * H), d["torso_rx"] * 1.05, 0.26 * H, m["shirt"], {"hips": 1.0},
                        segs=20, radius2=d["torso_rx"] * 0.8)
        self._footwear(mb, cos)
        if cos.get("kurta"):  # flared kurta hem over the hips, open at the sides like a real kameez
            hem = mb.cylinder((0, 0, d["hip_z"] - 0.06 * H), d["torso_rx"] * 1.08, 0.16 * H, m["shirt"],
                              {"hips": 1.0}, segs=28, radius2=d["torso_rx"] * 0.98)
            mb.delete([v for v in hem if abs(v.co.x) > d["torso_rx"] * 0.95 and v.co.z < d["hip_z"] - 0.03 * H])
        if "reflective_vest" in acc:
            for k in (0.3, 0.62):
                z = d["hip_z"] + d["torso_len"] * k
                rz = d["torso_len"] * 0.58
                f = math.sqrt(max(0.0, 1 - ((z - zc) / rz) ** 2))
                mb.torus((0, 0, z), 1.0, 0.03, m["stripe"], tw, segs=28, ring_segs=6,
                         scale=(d["torso_rx"] * f * 1.03, d["torso_ry"] * f * 1.03, 0.6))
        if "jacket" in acc:
            mb.torus((0, 0, d["neck_base"] - 0.005 * H), 0.05 * H, 0.014 * H, m["jacket"], {"chest": 1.0},
                     segs=20, ring_segs=6)
            mb.box((0, -d["torso_ry"] * 0.98, zc), (0.006 * H, 0.01 * H, d["torso_len"] * 0.85),
                   m["stripe"], tw)
        rig_bones = {b.name: b for b in self.rig.data.bones}

        def bone_pts(name):
            b = rig_bones[name]
            return Vector(b.head_local), Vector(b.tail_local)

        # accessories on the body
        if "belt" in acc:
            z = d["hip_z"] + 0.035 * H
            mb.torus((0, 0, z), 1.0, 0.018, m["belt"], {"hips": 1.0}, segs=28, ring_segs=6,
                     scale=(d["torso_rx"] * 0.98, d["torso_ry"] * 1.02 + d["belly"] * 0.05 * H, 0.9))
            mb.box((0, -d["torso_ry"] * 1.04, z), (0.05 * H, 0.012 * H, 0.035 * H), m["gold"], {"hips": 1.0})
        if "agent_badge" in acc:
            z = d["hip_z"] + 0.035 * H
            pos = (d["torso_rx"] * 0.5, -d["torso_ry"] * 0.95, z)
            mx = frame_matrix(pos, (0.45, -1, 0)) @ Matrix.Rotation(math.pi / 2, 4, "X")
            mb.cylinder(pos, 0.026 * H, 0.008 * H, m["gold"], {"hips": 1.0}, segs=5, matrix=mx)
            mb.box((pos[0], pos[1] - 0.004 * H, pos[2]), (0.012 * H, 0.004 * H, 0.012 * H), m["pupil"], {"hips": 1.0})
        if "emblem_L" in acc:
            z = d["hip_z"] + d["torso_len"] * 0.68
            rz = d["torso_len"] * 0.58
            f = math.sqrt(max(0.0, 1 - ((z - zc) / rz) ** 2))
            y = -d["torso_ry"] * f - 0.002 * H
            disc_m = frame_matrix((0, y, z), (0, -1, 0.25)) @ Matrix.Rotation(math.pi / 2, 4, "X")
            mb.cylinder((0, y, z), 0.062 * H, 0.012 * H, m["red"], {"chest": 1.0}, segs=24, matrix=disc_m)
            mb.torus((0, y, z), 0.062 * H, 0.008 * H, m["gold"], {"chest": 1.0}, segs=24, ring_segs=6,
                     matrix=disc_m)
            yl = y - 0.008 * H
            mb.box((-0.014 * H, yl, z + 0.006 * H), (0.016 * H, 0.008 * H, 0.07 * H), m["gold"], {"chest": 1.0})
            mb.box((0.006 * H, yl, z - 0.022 * H), (0.05 * H, 0.008 * H, 0.016 * H), m["gold"], {"chest": 1.0})
        if "wrench" in acc:
            h0, h1 = bone_pts("hand_R")
            grip = h0.lerp(h1, 0.5)
            top = grip + Vector((0, -0.02 * H, 0.11 * H))
            bot = grip + Vector((0, 0.01 * H, -0.06 * H))
            mb.capsule(bot, top, 0.012 * H, 0.012 * H, m["metal"], {"prop_R": 1.0}, segs=8)
            mb.torus(top + Vector((0, 0, 0.025 * H)), 0.026 * H, 0.009 * H, m["metal"], {"prop_R": 1.0},
                     segs=16, ring_segs=6, matrix=frame_matrix(top + Vector((0, 0, 0.025 * H)), (0, -1, 0)) @
                     Matrix.Rotation(math.pi / 2, 4, "X"))

    def _footwear(self, mb: MeshBuilder, cos: dict) -> None:
        """Shoes/boots as real shells around the feet; sandals as sole + straps."""
        m, H = self.m, self.d["H"]
        bones = {b.name: (Vector(b.head_local), Vector(b.tail_local)) for b in self.rig.data.bones}
        style = cos.get("shoe_style", "sneakers")
        for side in ("L", "R"):
            ankle, toe = bones[f"foot_{side}"]
            w = {f"foot_{side}": 1.0}
            heel = ankle + Vector((0, 0.025 * H, -ankle.z + 0.02 * H))
            tip = Vector((toe.x, toe.y - 0.012 * H, 0.022 * H))
            mid = heel.lerp(tip, 0.5)
            length = (tip - heel).length
            if style == "sandals":
                mb.sphere(mid + Vector((0, 0, -0.012 * H)), (0.036 * H, length * 0.58, 0.008 * H), m["sole"], w,
                          segs=16, rings=6)
                for t in (0.35, 0.7):
                    pos = heel.lerp(tip, t) + Vector((0, 0, 0.012 * H))
                    mb.torus(pos, 1.0, 0.12, m["sole"], w, segs=16, ring_segs=6,
                             scale=(0.032 * H, 0.012 * H, 0.025 * H))
                continue
            mb.sphere(mid + Vector((0, 0, 0.004 * H)), (0.042 * H, length * 0.6, 0.032 * H), m["shoes"], w, segs=20,
                      rings=12)
            mb.sphere(mid + Vector((0, 0, -0.016 * H)), (0.044 * H, length * 0.62, 0.01 * H), m["sole"], w, segs=20,
                      rings=6)
            if style == "boots":
                mb.cylinder(ankle + Vector((0, 0.004 * H, 0.05 * H)), 0.04 * H, 0.12 * H, m["shoes"],
                            {f"shin_{side}": 1.0}, segs=18, radius2=0.044 * H)

    def _waistcoat_shell(self, obj) -> None:
        """Embroidered waistcoat: torso faces of the body duplicated and pushed out along
        their normals, so it fits any body exactly and inherits the skin weights."""
        import bmesh

        d, H = self.d, self.d["H"]
        mats = obj.data.materials
        torso_idx = 0  # first slot painted by _weight_and_paint is the torso material
        mats.append(self.m["waistcoat"])
        wc_idx = len(mats) - 1
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        faces = [f for f in bm.faces if f.material_index == torso_idx
                 and not (f.calc_center_median().y < 0 and abs(f.calc_center_median().x) < d["torso_rx"] * 0.18)
                 and f.calc_center_median().z < d["neck_base"] - 0.012 * H]
        res = bmesh.ops.duplicate(bm, geom=faces)
        new_faces = [g for g in res["geom"] if isinstance(g, bmesh.types.BMFace)]
        new_verts = {v for f in new_faces for v in f.verts}
        bm.normal_update()
        for v in new_verts:
            v.co += v.normal * 0.007 * H
        for f in new_faces:
            f.material_index = wc_idx
        bm.to_mesh(obj.data)
        bm.free()

    # ------------------------------------------------------------------- head
    def _head(self, mb: MeshBuilder, acc: set) -> None:
        d, m = self.d, self.m
        r, hc = d["head_r"], d["head_c"]
        c = Vector((0, 0, hc))
        head_w = {"head": 1.0}
        mb.sphere(c, (r, r * 0.95, r * 1.02), m["skin"], head_w, segs=36, rings=24)
        for sx in (1, -1):  # soft cheeks with a hint of blush
            mb.sphere(c + Vector((sx * 0.48 * r, -0.66 * r, -0.3 * r)), (0.3 * r, 0.26 * r, 0.24 * r), m["blush"],
                      head_w, segs=16, rings=10)
        face = self.spec.get("face", {})
        # chin/jaw volume so the lower face reads as a face, not a ball
        mb.sphere(c + Vector((0, -0.25 * r, -0.42 * r)), (r * 0.7, r * 0.6, r * 0.55), m["skin"],
                  {"head": 0.6, "jaw": 0.4}, segs=20, rings=12)
        if face.get("ears", True):
            for sx in (1, -1):
                mb.sphere(c + Vector((sx * r * 0.96, 0.05 * r, -0.02 * r)), (0.12 * r, 0.09 * r, 0.2 * r),
                          m["skin"], head_w, segs=12, rings=8)
        nose = face.get("nose", "button")
        npos = c + Vector((0, -0.99 * r, -0.12 * r))
        if nose == "pointy":
            mb.cylinder(npos, 0.09 * r, 0.22 * r, m["skin_dark"], head_w, segs=10, radius2=0.01 * r,
                        matrix=frame_matrix(npos, (0, -1, -0.15)) @ Matrix.Rotation(-math.pi / 2, 4, "X"))
        else:
            k = 0.17 if nose == "round" else 0.12
            mb.sphere(npos, (k * r, k * r * 0.9, k * r * 0.9), m["skin_dark"], head_w, segs=12, rings=8)
        if face.get("moustache"):
            for sx in (1, -1):
                mpos = c + Vector((sx * 0.13 * r, -0.97 * r, -0.28 * r))
                mb.sphere(mpos, (0.15 * r, 0.06 * r, 0.05 * r), m["hair"], head_w, segs=12, rings=6,
                          matrix=Matrix.Translation(mpos) @ Matrix.Rotation(sx * 0.25, 4, "Y") @
                          Matrix.Diagonal((0.15 * r, 0.06 * r, 0.05 * r, 1)))
        self._hair(mb, c, r, acc)
        if "safety_helmet" in acc:
            dome = mb.sphere(c + Vector((0, 0.04 * r, 0.3 * r)), (r * 1.1, r * 1.1, r * 0.95), m["helmet"], head_w,
                             segs=24, rings=14)
            mb.delete([v for v in dome if v.co.z < hc + 0.3 * r])
            mb.cylinder(c + Vector((0, -0.12 * r, 0.32 * r)), r * 1.25, 0.035 * r, m["helmet"], head_w, segs=24)
            mb.box(c + Vector((0, 0.04 * r, 1.08 * r)), (0.12 * r, r * 2.0, 0.12 * r), m["helmet"], head_w)
        if "biker_helmet" in acc:
            shell = mb.sphere(c + Vector((0, 0.03 * r, 0.05 * r)), (r * 1.18, r * 1.16, r * 1.16), m["helmet"],
                              head_w, segs=24, rings=14)
            # open face: remove the front-lower part so the face stays visible
            mb.delete([v for v in shell if (v.co.y < -0.25 * r and v.co.z < hc + 0.45 * r) or v.co.z < hc - 0.55 * r])
            vpos = c + Vector((0, -0.85 * r, 0.62 * r))
            mb.sphere(vpos, (0.85 * r, 0.25 * r, 0.16 * r), m["visor"], head_w, segs=16, rings=8)
        if "police_cap" in acc:
            mb.cylinder(c + Vector((0, 0, 0.75 * r)), r * 0.95, 0.35 * r, m["shirt"], head_w, segs=20)
            mb.cylinder(c + Vector((0, -0.6 * r, 0.6 * r)), r * 0.6, 0.04 * r, m["pupil"], head_w, segs=16)

    def _hair(self, mb: MeshBuilder, c: Vector, r: float, acc: set) -> None:
        hair = self.spec.get("hair", {})
        style = hair.get("style", "short")
        m = self.m["hair"]
        hw = {"head": 1.0}
        if style == "bald" or "biker_helmet" in acc:
            return
        cap = mb.sphere(c + Vector((0, 0.03 * r, 0.04 * r)), (r * 1.06, r * 1.04, r * 1.05), m, hw, segs=48,
                        rings=32)

        def below_hairline(v) -> bool:
            # front hairline higher than the back so the forehead shows
            front = max(0.0, -(v.co.y) / r)
            limit = c.z + (-0.4 + 0.98 * front) * r
            if style == "bowl":
                limit = c.z + (0.05 + 0.25 * front) * r
            if style == "long":
                limit = c.z + (-0.9 + 1.2 * front) * r
            return v.co.z < limit

        if style == "bald_sides":
            mb.delete([v for v in cap if v.co.z > c.z + 0.35 * r or v.co.y < -0.2 * r or v.co.z < c.z - 0.45 * r])
            return
        # Tuck the hair below the hairline inside the head instead of deleting it:
        # the cap then meets the scalp along a smooth curve rather than a jagged edge.
        for v in cap:
            if below_hairline(v):
                v.co = c + (v.co - c).normalized() * r * 0.9
        if style in ("short_tuft", "spiky"):
            n = 3 if style == "short_tuft" else 7
            for i in range(n):
                if style == "short_tuft":
                    base = c + Vector(((i - 1) * 0.28 * r, -0.62 * r, 0.82 * r))
                    tip_dir = Vector(((i - 1) * 0.25, -0.75, 0.55)).normalized()
                    length = 0.42 * r
                else:
                    a = 2 * math.pi * i / n
                    base = c + Vector((0.5 * r * math.cos(a), 0.5 * r * math.sin(a), 0.85 * r))
                    tip_dir = Vector((0.5 * math.cos(a), 0.5 * math.sin(a), 0.9)).normalized()
                    length = 0.38 * r
                mx, _ = _cone_matrix(base, base + tip_dir * length)
                mb.cylinder(base, 0.2 * r, length, m, hw, segs=8, radius2=0.01 * r, matrix=mx)
        elif style == "curly":
            for i in range(11):
                a = 2 * math.pi * i / 11
                pos = c + Vector((0.78 * r * math.cos(a), 0.78 * r * math.sin(a) + 0.05 * r, 0.6 * r))
                mb.sphere(pos, (0.3 * r,) * 3, m, hw, segs=10, rings=6)
            mb.sphere(c + Vector((0, 0, 0.95 * r)), (0.45 * r,) * 3, m, hw, segs=12, rings=8)
        elif style == "long":
            mb.sphere(c + Vector((0, 0.45 * r, -0.7 * r)), (0.85 * r, 0.45 * r, 0.95 * r), m, hw, segs=16, rings=10)

    # ------------------------------------------------------------------- face
    def _face(self, mb: MeshBuilder) -> dict:
        """Eyes, lids, brows, mouth. Returns vertex index ranges for shape keys."""
        d, m = self.d, self.m
        r, hc = d["head_r"], d["head_c"]
        c = Vector((0, 0, hc))
        eye_size = float(self.spec.get("eye_size", 1.0))
        re_ = 0.28 * r * eye_size
        shapes = {"lids": [], "lashes": [], "mouth": None}
        next_tag = [1]

        def new_tag() -> int:
            mb.tag = next_tag[0]
            next_tag[0] += 1
            return mb.tag

        for side, sx in (("L", 1), ("R", -1)):
            n = Vector((sx * 0.34, -0.92, 0.1)).normalized()
            ec = c + Vector((n.x * r, n.y * r * 0.95, n.z * r)) * 0.9
            gaze = Vector((sx * 0.16, -1.0, 0.08)).normalized()  # eyes look forward, not sideways
            emx = frame_matrix(ec, gaze, (re_, re_ * 0.7, re_ * 1.1))
            mb.sphere(None, None, m["eye_white"], {"head": 1.0}, segs=18, rings=12, matrix=emx)
            # two-tone iris: dark limbal ring + lighter inner iris (reads as depth at small sizes)
            mb.sphere(None, None, m["iris_rim"], {"head": 1.0}, segs=20, rings=12,
                      matrix=emx @ Matrix.Translation((0, 0.76, -0.03)) @ Matrix.Diagonal((0.7, 0.34, 0.72, 1)))
            mb.sphere(None, None, m["iris"], {"head": 1.0}, segs=20, rings=12,
                      matrix=emx @ Matrix.Translation((0, 0.82, -0.05)) @ Matrix.Diagonal((0.56, 0.32, 0.56, 1)))
            mb.sphere(None, None, m["pupil"], {"head": 1.0}, segs=12, rings=8,
                      matrix=emx @ Matrix.Translation((0, 1.02, -0.03)) @ Matrix.Diagonal((0.36, 0.14, 0.38, 1)))
            mb.sphere(None, None, m["highlight"], {"head": 1.0}, segs=8, rings=6,
                      matrix=emx @ Matrix.Translation((0.22 * sx, 1.1, 0.24)) @ Matrix.Diagonal((0.16, 0.06, 0.16, 1)))
            mb.sphere(None, None, m["highlight"], {"head": 1.0}, segs=8, rings=6,
                      matrix=emx @ Matrix.Translation((-0.16 * sx, 1.08, -0.2)) @ Matrix.Diagonal((0.07, 0.04, 0.07, 1)))
            # eyelid: a skin sphere slightly bigger than the eye; Basis = folded cap, Blink = full cover
            tag = new_tag()
            lmx = emx @ Matrix.Diagonal((1.12, 1.18, 1.1, 1))
            mb.sphere(None, None, m["skin"], {"head": 1.0}, segs=18, rings=12, matrix=lmx)
            mb.tag = 0
            shapes["lids"].append((tag, lmx))
            # eyelashes along the lid rim; the Blink key swings them down with the lid
            tag = new_tag()
            rim_z = 0.8
            rad = math.sqrt(1 - 0.78 ** 2) * 1.04
            pts = []
            for k in range(9):
                phi = math.radians(-70 + k * 17.5)
                pts.append(lmx @ Vector((rad * math.sin(phi), rad * math.cos(phi), rim_z)))
            for a, b in zip(pts, pts[1:]):
                mb.capsule(a, b, 0.05 * re_, 0.05 * re_, m["pupil"], {"head": 1.0}, segs=6, caps=False)
            outer = pts[-1] if sx > 0 else pts[0]
            for k, (dx, dz) in enumerate(((0.35, 0.28), (0.45, 0.12))):
                mb.capsule(outer, outer + Vector((sx * dx * re_, -0.05 * re_, dz * re_)), 0.045 * re_, 0.015 * re_,
                           m["pupil"], {"head": 1.0}, segs=6, caps=False)
            mb.tag = 0
            shapes["lashes"].append((tag, lmx))
            # brow
            bn = Vector((sx * 0.36, -0.86, 0.46)).normalized()
            bc = c + bn * r * 1.02
            mb.sphere(None, None, m["hair"], {f"brow_{side}": 1.0}, segs=12, rings=6,
                      matrix=frame_matrix(bc, bn, (0.23 * r * eye_size, 0.07 * r, 0.068 * r)))
        # mouth
        mn = Vector((0, -0.93, -0.4)).normalized()
        mc = c + mn * r * 0.98
        mmx = frame_matrix(mc, mn)
        tag = new_tag()
        mb.sphere(None, None, m["mouth"], lambda co: {"head": 0.55, "jaw": 0.45} if co.z < mc.z else {"head": 1.0},
                  segs=24, rings=12, matrix=mmx @ Matrix.Diagonal((0.3 * r, 0.05 * r, 0.035 * r, 1)))
        mb.tag = 0
        shapes["mouth"] = (tag, mmx, r)
        return shapes

    def _shape_keys(self, obj, shapes: dict) -> None:
        mesh = obj.data
        basis = obj.shape_key_add(name="Basis", from_mix=False)
        keys = {k: obj.shape_key_add(name=k, from_mix=False) for k in SHAPE_KEYS}
        tags = [a.value for a in mesh.attributes["part"].data]

        def tagged(tag: int) -> list[int]:
            return [i for i, t in enumerate(tags) if t == tag]
        # Eyelids: Basis folds the lid into a thin cap above the eye; Blink restores the full sphere.
        for tag, lmx in shapes["lids"]:
            inv = lmx.inverted()
            for i in tagged(tag):
                full = mesh.vertices[i].co.copy()
                u = inv @ full
                if u.z < 0.78:
                    rad = math.hypot(u.x, u.y) or 1e-6
                    k = math.sqrt(1 - 0.78 ** 2) / rad
                    folded = lmx @ Vector((u.x * k, u.y * k, 0.78))
                else:
                    folded = full
                basis.data[i].co = folded
                mesh.vertices[i].co = folded
                for name, key in keys.items():
                    key.data[i].co = full if name == "Blink" else folded
        # Lashes: Blink rotates them about the lid's local X axis from the top rim to the bottom.
        for tag, lmx in shapes["lashes"]:
            inv = lmx.inverted()
            swing = Matrix.Rotation(math.radians(-100), 4, "X")
            for i in tagged(tag):
                base = mesh.vertices[i].co.copy()
                closed = lmx @ (swing @ (inv @ base))
                basis.data[i].co = base
                for name, key in keys.items():
                    key.data[i].co = closed if name == "Blink" else base
        # Mouth: positions from unit-sphere coords with width/height/curve per shape.
        tag, mmx, r = shapes["mouth"]
        inv = mmx.inverted()
        unit = {}
        for i in tagged(tag):
            u = inv @ mesh.vertices[i].co
            unit[i] = Vector((u.x / (0.3 * r), u.y / (0.05 * r), u.z / (0.035 * r)))

        def mouth(w, h, curve, depth=0.05):
            out = {}
            for i, u in unit.items():
                out[i] = mmx @ Vector((u.x * w * r, u.y * depth * r, u.z * h * r + curve * r * (u.x ** 2)))
            return out

        shapes_def = {
            "Basis": mouth(0.28, 0.03, 0.03), "Open": mouth(0.24, 0.2, 0.0, 0.07), "Wide": mouth(0.38, 0.08, 0.02),
            "Round": mouth(0.14, 0.15, 0.0, 0.07), "Smile": mouth(0.34, 0.05, 0.13), "Frown": mouth(0.28, 0.035, -0.1),
            # m/b/p: lips pressed into a thin, slightly wider line; f/v: lower lip tucked up under the teeth
            "MBP": mouth(0.3, 0.01, 0.0, 0.035), "FV": mouth(0.3, 0.055, -0.035, 0.06),
        }
        for i in unit:
            basis.data[i].co = shapes_def["Basis"][i]
            mesh.vertices[i].co = shapes_def["Basis"][i]
            for name, key in keys.items():
                key.data[i].co = shapes_def.get(name, shapes_def["Basis"])[i]

    # ------------------------------------------------------------------- cape
    def _cape(self, mb: MeshBuilder) -> None:
        d, H = self.d, self.d["H"]
        top_z = d["neck_base"] - 0.005 * H
        bot_z = d["ankle_z"] + 0.18 * H
        half_top = d["shoulder_w"] * 0.95
        half_bot = half_top * 1.75
        y0 = d["torso_ry"] + 0.025 * H

        def pt(u: float, v: float) -> Vector:
            half = half_top + (half_bot - half_top) * v
            x = (u * 2 - 1) * half
            y = y0 + 0.07 * H * v + 0.05 * H * (1 - (x / half) ** 2) * (0.3 + v)
            if v < 0.08:  # wrap around the shoulders
                y -= 0.03 * H * (1 - v / 0.08) * (abs(x) / half) ** 2
            return Vector((x, y, top_z + (bot_z - top_z) * v))

        def weights(co: Vector) -> dict:
            v = (top_z - co.z) / (top_z - bot_z)
            if v < 0.06:
                return {"chest": 1.0}
            w = {}
            for i, centre in enumerate((0.2, 0.55, 0.9)):
                w[f"cape_{i + 1}"] = max(0.0, 1 - abs(v - centre) / 0.35)
            tot = sum(w.values()) or 1
            return {k: x / tot for k, x in w.items()}

        mb.grid(12, 10, pt, self.m["cape"], weights)
        mb.materials[0].use_backface_culling = False


def _cone_matrix(base: Vector, tip: Vector):
    from blender.mesh_utils import segment_matrix

    return segment_matrix(base, tip)


def build_character(cid: str, spec: dict, collection) -> bpy.types.Object:
    return CharacterBuilder(cid, spec).build(collection)
