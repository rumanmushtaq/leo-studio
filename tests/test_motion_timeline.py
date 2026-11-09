"""Motion library maths and the scene timeline / shot planner."""
import math

from blender import motion_library as ml
from blender.motion_math import axis_angle, qmul, qslerp, sample_path, yaw_towards
from core.timeline_manager import DialogueAudio, TimelineManager
from utils.config import FPS, MIN_VIDEO_SECONDS, TRANSITION_SECONDS


def fake_audio(parsed, seconds=2.0):
    out = {}
    for s in parsed.scenes:
        for i, e in enumerate(s.events):
            if e.kind in ("dialogue", "narration"):
                did = TimelineManager.dialogue_id(s.id, i)
                n = int(seconds * FPS)
                out[did] = DialogueAudio(did, f"/tmp/{did}.wav", seconds,
                                         {"open": [0.5] * n, "wide": [0.1] * n, "round": [0.1] * n})
    return out


def test_village_location_keywords():
    from core.scene_manager import location_for

    assert location_for("Gagan pulls the buffalo in the village courtyard") == "village"
    assert location_for("گاؤں میں صبح") == "village"


def test_quaternions():
    q = axis_angle((0, 0, 1), 90)
    assert abs(qmul(q, q)[0] - math.cos(math.radians(90))) < 1e-9
    mid = qslerp((1, 0, 0, 0), q, 0.5)
    assert abs(mid[0] - math.cos(math.radians(22.5))) < 1e-9


def test_yaw_convention():
    assert abs(yaw_towards(0, -1)) < 1e-9          # facing camera (-Y)
    assert abs(yaw_towards(1, 0) - 90) < 1e-9       # facing +X


def test_walk_feet_planted():
    """During stance the foot moves backward at body speed -> zero world velocity."""
    p = {"H": 1.4, "speed": 1.5}
    dt = 1 / 240
    for t in (0.05, 0.15, 0.3):                     # left foot stance phase (0..0.5 s)
        y0 = ml.walk(t, 5, p)["loc"]["foot_ik_L"][1]
        y1 = ml.walk(t + dt, 5, p)["loc"]["foot_ik_L"][1]
        foot_rel_speed = (y1 - y0) / dt              # +Y = backwards relative to body
        assert abs(foot_rel_speed - p["speed"]) < 1e-6
        assert ml.walk(t, 5, p)["loc"]["foot_ik_L"][2] == 0.0


def test_gesture_masking_keeps_legs():
    base = ml.walk(0.2, 5, {"H": 1.4, "speed": 1.2})
    g = ml.wave(0.2, 2, {"H": 1.4})
    out = ml.blend_poses(base, g, 1.0, mask=list(g["rot"]))
    assert out["loc"]["foot_ik_L"] == base["loc"]["foot_ik_L"]
    assert all(abs(a - b) < 1e-9 for a, b in zip(out["rot"]["upper_arm_R"], g["rot"]["upper_arm_R"]))


def test_all_clips_evaluate():
    p = {"H": 1.5, "speed": 1.2, "hip_height": 0.7}
    for fn in list(ml.BODY_CLIPS.values()) + list(ml.GESTURE_CLIPS.values()):
        pose = fn(0.4, 2.0, p)
        assert pose["rot"] or pose["loc"]


def test_timeline_dialogue_order_and_no_overlap(parsed_leo, registry):
    tl = TimelineManager(registry).build(parsed_leo, fake_audio(parsed_leo))
    for sd in tl["scenes"]:
        ds = sd["dialogues"]
        assert all(a["end"] <= b["start"] for a, b in zip(ds, ds[1:]))
        assert all(d["end"] - d["start"] >= round(d["duration"] * FPS) for d in ds)
        assert ds[0]["start"] >= TRANSITION_SECONDS * FPS            # clear of the cross-fade
        assert ds[-1]["end"] <= sd["frame_count"] - TRANSITION_SECONDS * FPS
    ids = [d["id"] for sd in tl["scenes"] for d in sd["dialogues"]]
    assert len(ids) == len(set(ids)) == 19


def test_minimum_duration_extension(registry):
    from core.scene_manager import SceneManager
    from core.script_parser import ScriptParser

    p = ScriptParser().parse("Scene 1: Park\nLeo: Hi!\nScene 2: School\nLeo: Bye!\n")
    SceneManager(registry).enrich(p)
    tl = TimelineManager(registry).build(p, fake_audio(p, 1.0))
    assert tl["total_seconds"] >= MIN_VIDEO_SECONDS
    assert sum(len(s["dialogues"]) for s in tl["scenes"]) == 2      # nothing duplicated
    assert tl["extension_per_scene"] > 0


def test_camera_shots_cover_every_frame(parsed_leo, registry):
    tl = TimelineManager(registry).build(parsed_leo, fake_audio(parsed_leo))
    for sd in tl["scenes"]:
        shots = sd["camera_shots"]
        assert shots[0]["start"] == 0
        assert all(a["end"] == b["start"] for a, b in zip(shots, shots[1:]))
        assert shots[-1]["end"] >= sd["frame_count"] - 1
        types = {s["type"] for s in shots}
        assert "establishing" in types
    s2 = tl["scenes"][1]
    assert {"tracking", "low_angle"} <= {s["type"] for s in s2["camera_shots"]}


def test_entering_characters_start_offstage(parsed_leo, registry):
    tl = TimelineManager(registry).build(parsed_leo, fake_audio(parsed_leo))
    s2 = tl["scenes"][1]
    leo = next(c for c in s2["characters"] if c["id"] == "leo")
    start = sample_path(leo["path"], 0)
    assert start["z"] > 5                        # flies in from the sky
    landed = sample_path(leo["path"], s2["frame_count"] - 1)
    assert abs(landed["z"]) < 1e-6 and abs(landed["x"] - leo["slot"][0]) < 1e-3
    s1 = tl["scenes"][0]
    boss = next(c for c in s1["characters"] if c["id"] == "boss")
    assert sample_path(boss["path"], 0)["x"] > 6        # walks in from the right


def test_only_speaker_lipsyncs(parsed_leo, registry):
    tl = TimelineManager(registry).build(parsed_leo, fake_audio(parsed_leo))
    sd = tl["scenes"][0]
    n_lines = {c["id"]: len(c["lipsync"]) for c in sd["characters"]}
    assert n_lines == {"karim": 2, "boss": 1, "chintu": 0, "motu": 0}
