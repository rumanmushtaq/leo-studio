"""Reusable humanoid rig template (run inside Blender, except ``compute_dims``).

Bones: root, hips, spine, chest, neck, head, jaw, brow_L/R, shoulder/upper_arm/
forearm/hand L/R, thigh/shin/foot L/R, prop_R, optional cape_1..3, plus non-
deforming IK controls foot_ik_L/R. Legs use a 2-bone IK chain to foot_ik so
feet stay planted while walking; feet copy the IK control's rotation.
"""
from __future__ import annotations

import math

AGE_PROPORTIONS = {
    #          head_r  leg    torso  shoulder  arm_up  arm_lo
    "child": (0.155, 0.38, 0.25, 0.125, 0.165, 0.145),
    "teen":  (0.128, 0.43, 0.27, 0.118, 0.17, 0.15),
    "adult": (0.117, 0.45, 0.28, 0.122, 0.175, 0.155),
}


def compute_dims(spec: dict) -> dict:
    """Body measurements (metres) for a character design. Pure Python."""
    H = float(spec.get("height", 1.7))
    w = float(spec.get("build", {}).get("width", 1.0))
    belly = float(spec.get("build", {}).get("belly", 0.0))
    head_k, leg_k, torso_k, sh_k, up_k, lo_k = AGE_PROPORTIONS.get(spec.get("age_group", "adult"),
                                                                   AGE_PROPORTIONS["adult"])
    ankle_z = 0.045 * H
    hip_z = ankle_z + leg_k * H
    neck_base = hip_z + torso_k * H
    neck_top = neck_base + 0.032 * H
    head_r = head_k * H
    head_c = neck_top + head_r * 0.82
    return {
        "H": H, "width": w, "belly": belly, "ankle_z": ankle_z, "hip_z": hip_z, "neck_base": neck_base,
        "neck_top": neck_top, "head_r": head_r, "head_c": head_c, "torso_len": torso_k * H,
        "shoulder_w": sh_k * H * w * 1.1, "hip_w": 0.068 * H * min(w, 1.25), "torso_rx": 0.15 * H * w,
        "torso_ry": 0.105 * H * (w ** 0.5) + belly * 0.1 * H, "arm_up": up_k * H, "arm_lo": lo_k * H,
        "arm_r": 0.037 * H * (w ** 0.5), "thigh_r": 0.052 * H * (w ** 0.6), "shin_r": 0.039 * H * (w ** 0.5),
        "hand_r": (0.05 if spec.get("age_group") == "child" else 0.043) * H, "foot_len": 0.12 * H,
        "top_z": head_c + head_r,
    }


def _joint_layout(d: dict) -> list[tuple]:
    """Main skeleton placed on the joints of an imported base body."""
    J = {k: (tuple(v[0]), tuple(v[1])) for k, v in d["joints"].items()}
    h = lambda n: J[n][0]  # noqa: E731
    H = d["H"]
    nt = d["neck_top"]
    bones = [
        ("root", (0, 0, 0), (0, 0, 0.12 * H), None, False, False),
        ("hips", h("pelvis"), h("spine_01"), "root", True, False),
        ("spine", h("spine_01"), h("spine_03"), "hips", True, True),
        ("chest", h("spine_03"), h("neck_01"), "spine", True, True),
        ("neck", h("neck_01"), h("Head"), "chest", True, True),
        ("head", h("Head"), (0, h("Head")[1], d["head_c"] + d["head_r"]), "neck", True, True),
    ]
    for side, s in (("L", "l"), ("R", "r")):
        hand_end = J[f"middle_01_{s}"][1]
        knee = h(f"calf_{s}")
        knee = (knee[0], knee[1] - 0.012 * H, knee[2])  # small forward bend for the IK solver
        toe = J[f"ball_{s}"][1]
        bones += [
            (f"shoulder_{side}", h(f"clavicle_{s}"), h(f"upperarm_{s}"), "chest", True, False),
            (f"upper_arm_{side}", h(f"upperarm_{s}"), h(f"lowerarm_{s}"), f"shoulder_{side}", True, True),
            (f"forearm_{side}", h(f"lowerarm_{s}"), h(f"hand_{s}"), f"upper_arm_{side}", True, True),
            (f"hand_{side}", h(f"hand_{s}"), hand_end, f"forearm_{side}", True, True),
            (f"thigh_{side}", h(f"thigh_{s}"), knee, "hips", True, False),
            (f"shin_{side}", knee, h(f"foot_{s}"), f"thigh_{side}", True, True),
            (f"foot_{side}", h(f"foot_{s}"), toe, f"shin_{side}", True, True),
            (f"foot_ik_{side}", h(f"foot_{s}"), toe, "root", False, False),
        ]
    del nt
    return bones


def bone_layout(d: dict, cape: bool) -> list[tuple]:
    """(name, head, tail, parent, deform, connected) for every bone."""
    if "joints" in d:
        return _face_and_extras(d, _joint_layout(d), cape)
    H = d["H"]
    hz, nb, nt = d["hip_z"], d["neck_base"], d["neck_top"]
    spine_mid = hz + d["torso_len"] * 0.5
    r, hc = d["head_r"], d["head_c"]
    bones = [
        ("root", (0, 0, 0), (0, 0, 0.12 * H), None, False, False),
        ("hips", (0, 0, hz), (0, 0, hz + 0.08 * H), "root", True, False),
        ("spine", (0, 0, hz + 0.08 * H), (0, 0, spine_mid), "hips", True, True),
        ("chest", (0, 0, spine_mid), (0, 0, nb), "spine", True, True),
        ("neck", (0, 0, nb), (0, 0, nt), "chest", True, True),
        ("head", (0, 0, nt), (0, 0, hc + r), "neck", True, True),
    ]
    for side, sx in (("L", 1), ("R", -1)):
        sh = (d["shoulder_w"] * sx, 0.0, nb - 0.035 * H)
        ang = math.radians(12)
        elbow = (sh[0] + sx * d["arm_up"] * math.sin(ang), -0.004 * H, sh[2] - d["arm_up"] * math.cos(ang))
        wrist = (elbow[0] + sx * d["arm_lo"] * math.sin(ang), -0.016 * H, elbow[2] - d["arm_lo"] * math.cos(ang))
        hand_end = (wrist[0] + sx * 0.06 * H * math.sin(ang), wrist[1], wrist[2] - 0.06 * H * math.cos(ang))
        bones += [
            (f"shoulder_{side}", (0.03 * H * sx, 0, nb - 0.02 * H), sh, "chest", True, False),
            (f"upper_arm_{side}", sh, elbow, f"shoulder_{side}", True, True),
            (f"forearm_{side}", elbow, wrist, f"upper_arm_{side}", True, True),
            (f"hand_{side}", wrist, hand_end, f"forearm_{side}", True, True),
        ]
        hip = (d["hip_w"] * sx, 0, hz)
        knee = (d["hip_w"] * sx, -0.018 * H, (hz + d["ankle_z"]) / 2)
        ankle = (d["hip_w"] * sx, 0, d["ankle_z"])
        toe = (d["hip_w"] * sx, -d["foot_len"], 0.012 * H)
        bones += [
            (f"thigh_{side}", hip, knee, "hips", True, False),
            (f"shin_{side}", knee, ankle, f"thigh_{side}", True, True),
            (f"foot_{side}", ankle, toe, f"shin_{side}", True, True),
            (f"foot_ik_{side}", ankle, toe, "root", False, False),
        ]
    return _face_and_extras(d, bones, cape)


def _face_and_extras(d: dict, bones: list[tuple], cape: bool) -> list[tuple]:
    """Jaw, brows, hand prop and cape bones (shared by both layouts)."""
    H = d["H"]
    r, hc, nb = d["head_r"], d["head_c"], d["neck_base"]
    names = [b[0] for b in bones]
    if "jaw" not in names:
        bones.append(("jaw", (0, -0.1 * r, hc - 0.05 * r), (0, -0.8 * r, hc - 0.5 * r), "head", True, False))
        for side, sx in (("L", 1), ("R", -1)):
            bx = 0.38 * r * sx
            bones.append((f"brow_{side}", (bx, -0.86 * r, hc + 0.42 * r), (bx * 1.05, -1.06 * r, hc + 0.5 * r),
                          "head", True, False))
    bones.append(("prop_R", bones[[b[0] for b in bones].index("hand_R")][2],
                  (bones[[b[0] for b in bones].index("hand_R")][2][0], -0.1 * H,
                   bones[[b[0] for b in bones].index("hand_R")][2][2]), "hand_R", True, False))
    if cape:
        y0 = d["torso_ry"] + 0.03 * H
        z0 = nb - 0.01 * H
        z_end = d["ankle_z"] + 0.2 * H
        step = (z0 - z_end) / 3
        prev = "chest"
        for i in range(3):
            head = (0, y0 + 0.02 * H * i, z0 - step * i)
            tail = (0, y0 + 0.02 * H * (i + 1), z0 - step * (i + 1))
            bones.append((f"cape_{i + 1}", head, tail, prev, True, i > 0))
            prev = f"cape_{i + 1}"
    return bones


def build_rig(name: str, dims: dict, collection, cape: bool = False):
    import bpy

    arm_data = bpy.data.armatures.new(name)
    arm = bpy.data.objects.new(name, arm_data)
    collection.objects.link(arm)
    view_layer = bpy.context.view_layer
    if arm.name not in view_layer.objects:
        bpy.context.scene.collection.objects.link(arm)
    view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm_data.edit_bones
    for bname, head, tail, parent, deform, connected in bone_layout(dims, cape):
        b = eb.new(bname)
        b.head, b.tail = head, tail
        b.use_deform = deform
        if parent:
            b.parent = eb[parent]
            b.use_connect = connected
    bpy.ops.object.mode_set(mode="OBJECT")

    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"
    for side in ("L", "R"):
        ik = arm.pose.bones[f"shin_{side}"].constraints.new("IK")
        ik.name = "IK"
        ik.target = arm
        ik.subtarget = f"foot_ik_{side}"
        ik.chain_count = 2
        ik.use_tail = True
        cr = arm.pose.bones[f"foot_{side}"].constraints.new("COPY_ROTATION")
        cr.name = "FootRot"
        cr.target = arm
        cr.subtarget = f"foot_ik_{side}"
    arm_data.display_type = "STICK"
    arm.show_in_front = True
    return arm
