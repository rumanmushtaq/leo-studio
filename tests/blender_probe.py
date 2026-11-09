"""Run inside Blender by test_blender.py: dump facts about built assets/scenes as JSON."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bpy  # noqa: E402

out = sys.argv[sys.argv.index("--") + 1]
facts = {"objects": {}, "markers": [m.name for m in bpy.context.scene.timeline_markers],
         "frame_end": bpy.context.scene.frame_end, "camera": bpy.context.scene.camera.name
         if bpy.context.scene.camera else None, "actions": [a.name for a in bpy.data.actions]}
for o in bpy.data.objects:
    d = {"type": o.type}
    if o.type == "ARMATURE":
        d["bones"] = sorted(b.name for b in o.data.bones)
        d["ik"] = [pb.name for pb in o.pose.bones for c in pb.constraints if c.type == "IK"]
        d["animated"] = bool(o.animation_data and o.animation_data.action)
        if d["animated"]:
            sc = bpy.context.scene
            sc.frame_set(10)
            a = o.pose.bones["upper_arm_R"].matrix.copy()
            sc.frame_set(min(sc.frame_end, 200))
            d["arm_moves"] = (o.pose.bones["upper_arm_R"].matrix - a).to_3x3().median_scale != 0 or \
                any(abs(x) > 1e-4 for row in (o.pose.bones["upper_arm_R"].matrix - a) for x in row)
    if o.type == "MESH":
        d["verts"] = len(o.data.vertices)
        d["groups"] = sorted(g.name for g in o.vertex_groups)
        d["materials"] = [(m.name, [round(c, 4) for c in m.diffuse_color]) for m in o.data.materials if m]
        if o.data.shape_keys:
            d["shape_keys"] = [k.name for k in o.data.shape_keys.key_blocks]
            d["shape_animated"] = bool(o.data.shape_keys.animation_data and o.data.shape_keys.animation_data.action)
        d["modifiers"] = [m.type for m in o.modifiers]
    facts["objects"][o.name] = d
json.dump(facts, open(out, "w"))
