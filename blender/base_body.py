"""Adapter for the CC0 Quaternius "Universal Base Characters" bodies (run inside Blender).

The base body (professionally modelled, 7k vertices, UE-style 65-bone rig) is:
  1. re-proportioned per character by scaling its bones (child limbs, build
     width, Motu's belly) and posed from T-pose into our A-pose,
  2. baked (armature applied) and uniformly scaled so the neck meets the
     cartoon head at the character's designed height,
  3. re-skinned to *our* rig: its vertex groups are merged into our bone
     names, so the existing motion library, leg IK and lip-sync work unchanged,
  4. stripped of its realistic head (the cartoon head replaces it).
Costume colours are painted by body region afterwards (character_builder).
"""
from __future__ import annotations

import math
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

BASE_DIR = Path(__file__).resolve().parent.parent / "assets" / "characters" / "base" / "quaternius_ubc"
BASE_FILES = {"male": "Superhero_Male_FullBody.gltf", "female": "Superhero_Female_FullBody.gltf"}

GROUP_MAP = {
    "pelvis": "hips", "spine_01": "spine", "spine_02": "chest", "spine_03": "chest", "neck_01": "neck",
    "Head": "head",
}
for _s, _S in (("l", "L"), ("r", "R")):
    GROUP_MAP.update({f"clavicle_{_s}": f"shoulder_{_S}", f"upperarm_{_s}": f"upper_arm_{_S}",
                      f"lowerarm_{_s}": f"forearm_{_S}", f"hand_{_s}": f"hand_{_S}", f"thigh_{_s}": f"thigh_{_S}",
                      f"calf_{_s}": f"shin_{_S}", f"foot_{_s}": f"foot_{_S}", f"ball_{_s}": f"foot_{_S}"})
    GROUP_MAP[f"ball_leaf_{_s}"] = f"foot_{_S}"
    for _f in ("index", "middle", "ring", "pinky", "thumb"):
        for _k in ("01", "02", "03", "04_leaf"):
            GROUP_MAP[f"{_f}_{_k}_{_s}"] = f"hand_{_S}"


def available(gender: str = "male") -> bool:
    return (BASE_DIR / BASE_FILES.get(gender, BASE_FILES["male"])).exists()


def _world_quat(arm, bone_name: str):
    return (arm.matrix_world @ arm.data.bones[bone_name].matrix_local).to_quaternion()


def _rotate_bone_world(arm, name: str, world_from: Vector, world_to: Vector) -> None:
    """Pose-rotate a bone so its world direction goes from ``world_from`` to ``world_to``."""
    pb = arm.pose.bones[name]
    pb.rotation_mode = "QUATERNION"
    q_world = world_from.normalized().rotation_difference(world_to.normalized())
    r = _world_quat(arm, name)
    pb.rotation_quaternion = r.inverted() @ q_world @ r


# Other humanoid skeletons mapped onto the UE/Quaternius names used here.
_SIDE = {"Left": "l", "Right": "r"}
MIXAMO = {"Hips": "pelvis", "Spine": "spine_01", "Spine1": "spine_02", "Spine2": "spine_03", "Neck": "neck_01",
          "Head": "Head"}
for _side, _s in _SIDE.items():
    MIXAMO.update({f"{_side}Shoulder": f"clavicle_{_s}", f"{_side}Arm": f"upperarm_{_s}",
                   f"{_side}ForeArm": f"lowerarm_{_s}", f"{_side}Hand": f"hand_{_s}", f"{_side}UpLeg": f"thigh_{_s}",
                   f"{_side}Leg": f"calf_{_s}", f"{_side}Foot": f"foot_{_s}", f"{_side}ToeBase": f"ball_{_s}"})
    for _f, _uf in (("Index", "index"), ("Middle", "middle"), ("Ring", "ring"), ("Pinky", "pinky"), ("Thumb", "thumb")):
        for _k in (1, 2, 3):
            MIXAMO[f"{_side}Hand{_f}{_k}"] = f"{_uf}_0{_k}_{_s}"
REQUIRED_BONES = ["pelvis", "spine_01", "spine_03", "neck_01", "Head", "clavicle_l", "upperarm_l", "lowerarm_l",
                  "hand_l", "thigh_l", "calf_l", "foot_l", "ball_l", "clavicle_r", "upperarm_r", "lowerarm_r",
                  "hand_r", "thigh_r", "calf_r", "foot_r", "ball_r"]


def _canonical(name: str) -> str:
    """Strip rig prefixes ('mixamorig:', 'mixamorig1:', 'Armature|') and map to canonical names."""
    base = name.split(":")[-1].split("|")[-1]
    return MIXAMO.get(base, base)


def _fix_missing_textures(objects) -> None:
    """Image textures whose files are missing render magenta; fall back to plain colour."""
    import os

    for o in objects:
        if o.type != "MESH":
            continue
        for mat in o.data.materials:
            if not mat or not mat.use_nodes:
                continue
            for node in list(mat.node_tree.nodes):
                if node.type != "TEX_IMAGE" or node.image is None:
                    continue
                img = node.image
                path = bpy.path.abspath(img.filepath) if img.filepath else ""
                if img.packed_file is None and (not path or not os.path.exists(path)):
                    for link in list(node.outputs[0].links):
                        mat.node_tree.links.remove(link)
                    mat.node_tree.nodes.remove(node)


def import_model(path: Path):
    """Import a humanoid model file; returns (armature, largest skinned mesh, other new objects)."""
    path = Path(path)
    before = set(bpy.data.objects)
    ext = path.suffix.lower()
    if ext in (".gltf", ".glb"):
        bpy.ops.import_scene.gltf(filepath=str(path), import_shading="NORMALS")
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=str(path), automatic_bone_orientation=False)
    elif ext == ".blend":
        with bpy.data.libraries.load(str(path), link=False) as (src, dst):
            dst.objects = list(src.objects)
        for o in dst.objects:
            if o is not None:
                bpy.context.scene.collection.objects.link(o)
    else:
        raise ValueError(f"Unsupported character file type: {ext} (use .glb, .gltf, .fbx or .blend)")
    new = [o for o in bpy.data.objects if o not in before]
    arms = [o for o in new if o.type == "ARMATURE"]
    if not arms:
        raise ValueError(f"{path.name}: no armature found; the character must be rigged (humanoid skeleton)")
    arm = max(arms, key=lambda o: len(o.data.bones))
    meshes = [o for o in new if o.type == "MESH" and any(m.type == "ARMATURE" for m in o.modifiers)]
    if not meshes:
        raise ValueError(f"{path.name}: no skinned mesh found")
    body = max(meshes, key=lambda o: len(o.data.vertices))
    # canonical bone + vertex-group names, so every rig maps onto ours the same way
    for b in arm.data.bones:
        b.name = _canonical(b.name)
    for o in meshes:
        for g in o.vertex_groups:
            g.name = _canonical(g.name)
    _fix_missing_textures(new)
    missing = [b for b in REQUIRED_BONES if b not in arm.data.bones]
    if missing:
        raise ValueError(f"{path.name}: skeleton is not a supported humanoid rig; missing bones {missing[:6]}")
    return arm, body, [o for o in new if o not in (arm, body)]


def build_base_body(cid: str, spec: dict, dims: dict, collection):
    """Import, re-proportion and bake the base body. Returns (mesh_object, joints).

    ``spec["model_file"]`` imports a user character instead of the CC0 base body;
    with ``spec["keep_head"]`` its own head and face are kept (no cartoon head).
    """
    gender = "female" if spec.get("gender") == "female" else "male"
    path = Path(spec["model_file"]) if spec.get("model_file") else BASE_DIR / BASE_FILES[gender]
    arm, body, others = import_model(path)
    keep = {body}
    if spec.get("keep_head"):  # keep eyes/teeth/brows etc. of an imported character, merged into the body
        keep |= {o for o in others if o.type == "MESH"}
    for o in others:
        if o not in keep:
            bpy.data.objects.remove(o, do_unlink=True)
    extra_parts = [o for o in keep if o is not body]
    if extra_parts:  # join kept face parts into the body; join merges vertex groups by name
        view_layer = bpy.context.view_layer
        for o in view_layer.objects:
            o.select_set(False)
        for o in [body, *extra_parts]:
            if o.name not in view_layer.objects:
                bpy.context.scene.collection.objects.link(o)
            o.select_set(True)
        view_layer.objects.active = body
        bpy.ops.object.join()
    for b in arm.data.bones:
        b.inherit_scale = "NONE"  # girth scaling must not leak into child bones
    pbs = arm.pose.bones

    # --- proportions --------------------------------------------------------
    age = spec.get("age_group", "adult")
    w = float(spec.get("build", {}).get("width", 1.0))
    belly = float(spec.get("build", {}).get("belly", 0.0))
    leg_len = {"child": 0.86, "teen": 0.95}.get(age, 1.0)
    arm_len = {"child": 0.9, "teen": 0.96}.get(age, 1.0)
    girth = {"child": 0.88, "teen": 0.92}.get(age, 1.0) * w
    for name in ("pelvis", "spine_01", "spine_02", "spine_03"):
        g = girth * (1 + belly * (1.7 if name in ("spine_01", "spine_02") else 0.8 if name == "pelvis" else 0.3))
        pbs[name].scale = (g, 1.0, g)
    for s in ("l", "r"):
        pbs[f"thigh_{s}"].scale = (girth * (1 + belly * 0.4), leg_len, girth * (1 + belly * 0.4))
        pbs[f"calf_{s}"].scale = (girth, leg_len, girth)
        pbs[f"upperarm_{s}"].scale = (girth * 0.95, arm_len, girth * 0.95)
        pbs[f"lowerarm_{s}"].scale = (girth * 0.95, arm_len, girth * 0.95)
        pbs[f"hand_{s}"].scale = (1.12, 1.12, 1.12)  # slightly bigger cartoon hands
    bpy.context.view_layer.update()
    # --- T-pose -> A-pose (arms 12 degrees from vertical by default) ---------
    for s, sx in (("l", 1), ("r", -1)):
        head = arm.matrix_world @ pbs[f"upperarm_{s}"].head
        tail = arm.matrix_world @ pbs[f"upperarm_{s}"].tail
        if abs(head.x) < 1e-6:
            continue
        side = 1 if head.x > 0 else -1
        # wider rest spread for round characters so arms clear the belly in every gesture
        spread = math.radians(float(spec.get("arm_spread", 12)))
        target = Vector((side * math.sin(spread), 0.0, -math.cos(spread)))
        _rotate_bone_world(arm, f"upperarm_{s}", tail - head, target)
        bpy.context.view_layer.update()
    # slight natural knee bend so the leg IK has a preferred direction
    bpy.context.view_layer.update()

    # --- bake deformed mesh into world space --------------------------------
    # one subdivision level: smoother surface and finer costume paint borders
    sub = body.modifiers.new("Subdivide", "SUBSURF")
    sub.levels = sub.render_levels = 1
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    mesh = bpy.data.meshes.new_from_object(body.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
    mesh.transform(body.matrix_world)
    joints = {}
    for pb in pbs:
        joints[pb.name] = (arm.matrix_world @ pb.head, arm.matrix_world @ pb.tail)
    group_names = [g.name for g in body.vertex_groups]

    if "middle_01_l" not in joints:
        for s_ in ("l", "r"):
            joints[f"middle_01_{s_}"] = joints[f"hand_{s_}"]
    # --- uniform scale: base neck top -> designed neck top (or full height when the
    # imported head is kept); feet on the ground ---
    if spec.get("keep_head"):
        zs = [v.co.z for v in mesh.vertices]
        s = dims["H"] / max(1e-6, max(zs) - min(zs))
    else:
        s = dims["neck_top"] / max(1e-6, joints["Head"][0].z)
    min_z = min(v.co.z for v in mesh.vertices) * s
    T = Matrix.Translation((0, 0, -min_z)) @ Matrix.Scale(s, 4)
    mesh.transform(T)
    joints = {k: (T @ a, T @ b) for k, (a, b) in joints.items()}

    out = bpy.data.objects.new(f"{cid}_skinbody", mesh)
    collection.objects.link(out)
    for g in group_names:
        out.vertex_groups.new(name=g)
    bpy.data.objects.remove(body, do_unlink=True)
    bpy.data.objects.remove(arm, do_unlink=True)
    if not spec.get("model_file"):
        mesh.materials.clear()  # the base body is repainted with the character's costume
    for poly in mesh.polygons:
        poly.use_smooth = True
    return out, joints


def remap_groups(obj) -> None:
    """Merge the base rig's vertex groups into our bone names (weights summed)."""
    old = {g.index: g.name for g in obj.vertex_groups}
    acc: dict[int, dict[str, float]] = {}
    for v in obj.data.vertices:
        d: dict[str, float] = {}
        for ge in v.groups:
            name = GROUP_MAP.get(old.get(ge.group, ""))
            if name and ge.weight > 1e-4:
                d[name] = d.get(name, 0.0) + ge.weight
        acc[v.index] = d
    # any vertex left without weights would stay frozen in the rest pose and stretch:
    # give it the weights of its nearest weighted neighbour
    weighted = [(obj.data.vertices[i].co, d) for i, d in acc.items() if d]
    if weighted:
        from mathutils import kdtree

        kd = kdtree.KDTree(len(weighted))
        for k, (co, _) in enumerate(weighted):
            kd.insert(co, k)
        kd.balance()
        for i, d in acc.items():
            if not d:
                acc[i] = dict(weighted[kd.find(obj.data.vertices[i].co)[1]][1])
    for g in list(obj.vertex_groups):
        obj.vertex_groups.remove(g)
    groups: dict[str, bpy.types.VertexGroup] = {}
    for vi, d in acc.items():
        tot = sum(d.values()) or 1.0
        for name, wgt in d.items():
            if name not in groups:
                groups[name] = obj.vertex_groups.new(name=name)
            groups[name].add([vi], wgt / tot, "REPLACE")


def remove_head(obj, neck_top_z: float) -> None:
    """Delete the realistic head; the cartoon head is attached at the same joint."""
    import bmesh

    gi = obj.vertex_groups.get("head")
    if gi is None:
        return
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    deform = bm.verts.layers.deform.verify()
    doomed = [v for v in bm.verts if v[deform].get(gi.index, 0.0) > 0.45 and v.co.z > neck_top_z - 0.005]
    bmesh.ops.delete(bm, geom=doomed, context="VERTS")
    bm.to_mesh(obj.data)
    bm.free()


def dims_from_joints(d: dict, joints: dict, obj) -> dict:
    """Update body measurements from the baked base body so accessories fit it."""
    j = {k: v[0] for k, v in joints.items()}
    tail = {k: v[1] for k, v in joints.items()}
    d = dict(d)
    d["hip_z"] = j["pelvis"].z
    d["neck_base"] = j["neck_01"].z
    d["neck_top"] = j["Head"].z
    d["head_c"] = d["neck_top"] + d["head_r"] * 0.82
    d["top_z"] = d["head_c"] + d["head_r"]
    d["torso_len"] = d["neck_base"] - d["hip_z"]
    d["ankle_z"] = j["foot_l"].z
    d["shoulder_w"] = abs(j["upperarm_l"].x)
    d["hip_w"] = abs(j["thigh_l"].x)
    d["foot_len"] = abs(tail["ball_l"].y - j["foot_l"].y)
    zc = d["hip_z"] + 0.7 * d["torso_len"]
    band = [v.co for v in obj.data.vertices if abs(v.co.z - zc) < 0.02 * d["H"] and abs(v.co.x) < d["shoulder_w"] * 0.8]
    if band:
        d["torso_rx"] = max(abs(c.x) for c in band)
        d["torso_ry"] = max(abs(c.y) for c in band)
    d["joints"] = {k: [list(map(float, a)), list(map(float, b))] for k, (a, b) in joints.items()}
    return d
