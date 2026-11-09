"""Blender integration: character asset, rig, shape keys, scene build, asset reuse."""
import json
import re

import pytest

from blender.blender_manager import BlenderManager
from core.timeline_manager import TimelineManager
from tests.conftest import ROOT, requires_blender
from tests.test_motion_timeline import fake_audio

pytestmark = [pytest.mark.blender, requires_blender]


def probe(bm: BlenderManager, blend, tmp_path, name):
    out = tmp_path / f"{name}.json"
    bm.run([str(blend), "-P", str(ROOT / "tests" / "blender_probe.py"), "--", str(out)], tmp_path / f"{name}.log")
    return json.loads(out.read_text())


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """Build Leo + Karim assets and scene 1 and 2 of the Leo story once."""
    from core.character_manager import CharacterRegistry
    from core.scene_manager import SceneManager
    from core.script_parser import ScriptParser
    from tests.conftest import LEO_SCRIPT

    tmp = tmp_path_factory.mktemp("blend")
    reg = CharacterRegistry(registry_file=tmp / "reg.json")
    p = ScriptParser().parse(LEO_SCRIPT)
    SceneManager(reg).enrich(p)
    bm = BlenderManager()
    chars = sorted({c for s in p.scenes[:2] for c in s.characters})
    job = {"characters": [{"id": c, "spec": reg.characters[c].data, "blend_path": str(tmp / f"{c}.blend")}
                          for c in chars]}
    bm.run_script("run_build_characters.py", job, tmp / "cj.json", tmp / "chars.log")
    tl = TimelineManager(reg).build(p, fake_audio(p))
    for sd in tl["scenes"][:2]:
        job = {"scene": sd, "fps": 24, "quality": "preview",
               "character_assets": {c["id"]: str(tmp / f"{c['id']}.blend") for c in sd["characters"]},
               "frames_dir": str(tmp / f"frames_{sd['id']}"), "out_blend": str(tmp / f"scene_{sd['id']}.blend")}
        bm.run_script("run_build_scene.py", job, tmp / f"sj{sd['id']}.json", tmp / f"scene{sd['id']}.log")
    return bm, tmp, tl


def test_character_asset(built, tmp_path):
    bm, tmp, _ = built
    f = probe(bm, tmp / "leo.blend", tmp_path, "leo")
    rig = f["objects"]["leo_rig"]
    for b in ("root", "hips", "spine", "chest", "neck", "head", "jaw", "brow_L", "upper_arm_L", "forearm_R",
              "hand_L", "thigh_R", "shin_L", "foot_R", "foot_ik_L", "cape_1", "cape_3"):
        assert b in rig["bones"]
    assert sorted(rig["ik"]) == ["shin_L", "shin_R"]
    face = f["objects"]["leo_face"]
    assert {"Blink", "Open", "Wide", "Round", "Smile", "Frown", "MBP", "FV"} <= set(face["shape_keys"])
    body = f["objects"]["leo_body"]
    assert "ARMATURE" in body["modifiers"] and "SOLIDIFY" in body["modifiers"]
    assert set(body["groups"]) <= set(rig["bones"])
    assert "leo_cape" in f["objects"]
    skin = f["objects"]["leo_skinbody"]                    # CC0 base body re-skinned to our rig
    assert skin["verts"] > 5000 and "ARMATURE" in skin["modifiers"]
    assert {"hips", "chest", "head", "hand_L", "foot_R"} <= set(skin["groups"]) <= set(rig["bones"])


def test_scene_animated_with_camera(built, tmp_path):
    bm, tmp, tl = built
    f = probe(bm, tmp / "scene_2.blend", tmp_path, "s2")
    assert f["frame_end"] == tl["scenes"][1]["frame_count"] - 1
    assert f["camera"] == "scene_camera"
    assert any(m.startswith("tracking") for m in f["markers"]) and any(m.startswith("low_angle") for m in f["markers"])
    rigs = {k: v for k, v in f["objects"].items() if v["type"] == "ARMATURE"}
    assert set(rigs) == {"leo_rig", "boss_rig", "chintu_rig", "motu_rig", "karim_rig"}
    assert all(r["animated"] for r in rigs.values())
    assert f["objects"]["leo_face"]["shape_animated"]
    assert any(k.startswith("fx_impact") for k in f["objects"])


def test_same_character_asset_in_every_scene(built, tmp_path):
    """Karim is appended from one .blend: identical geometry and materials in both scenes."""
    bm, tmp, _ = built
    a = probe(bm, tmp / "scene_1.blend", tmp_path, "a")["objects"]
    b = probe(bm, tmp / "scene_2.blend", tmp_path, "b")["objects"]
    for name in ("karim_body", "karim_face"):
        assert a[name]["verts"] == b[name]["verts"]
        # shared materials appended twice get Blender's ".001" suffix; content must match
        strip = lambda mats: [(re.sub(r"\.\d{3}$", "", n), c) for n, c in mats]  # noqa: E731
        assert strip(a[name]["materials"]) == strip(b[name]["materials"])


def test_render_one_frame(built, tmp_path):
    bm, tmp, _ = built
    out = tmp_path / "f_####"
    bm.run([str(tmp / "scene_2.blend"), "-o", str(out), "-F", "JPEG", "-f", "100"], tmp_path / "r.log")
    from PIL import Image, ImageStat

    img = Image.open(tmp_path / "f_0100.jpg")
    assert img.size == (640, 360)                       # preview = 50 % of 1280x720
    assert max(ImageStat.Stat(img).stddev) > 20         # not a blank frame


def test_import_external_model(tmp_path):
    """A humanoid glTF (UE-style skeleton) imported as a user character, both modes."""
    from blender.blender_manager import BlenderManager

    model = ROOT / "assets" / "characters" / "base" / "quaternius_ubc" / "Superhero_Female_FullBody.gltf"
    base = {"name": "Zara", "role": "neutral", "age_group": "adult", "gender": "female", "height": 1.65,
            "build": {"width": 1.0, "belly": 0}, "skin": [0.85, 0.63, 0.47], "eye_color": [0.2, 0.13, 0.07],
            "hair": {"style": "long", "color": [0.1, 0.07, 0.05]}, "face": {"nose": "button"},
            "costume": {"shirt": [0.9, 0.3, 0.5], "pants": [0.2, 0.25, 0.45], "shoes": [0.2, 0.15, 0.1]},
            "accessories": [], "model_file": str(model)}
    bm = BlenderManager()
    for cid, extra in (("zara_own", {"keep_head": True}), ("zara_toon", {"recolor": True})):
        job = {"characters": [{"id": cid, "spec": dict(base, **extra), "blend_path": str(tmp_path / f"{cid}.blend")}]}
        bm.run_script("run_build_characters.py", job, tmp_path / f"{cid}.json", tmp_path / f"{cid}.log")
        f = probe(bm, tmp_path / f"{cid}.blend", tmp_path, cid)["objects"]
        rig = f[f"{cid}_rig"]
        assert sorted(rig["ik"]) == ["shin_L", "shin_R"]
        if cid == "zara_own":
            assert f"{cid}_face" in f and f[f"{cid}_face"]["verts"] > 5000   # imported head kept, used as face
        else:
            assert f[f"{cid}_skinbody"]["verts"] > 5000 and "leo_face" not in f
            assert {"Blink", "Open", "Smile"} <= set(f[f"{cid}_face"]["shape_keys"])
