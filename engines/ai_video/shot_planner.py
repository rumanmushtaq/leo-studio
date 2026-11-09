"""Turn the studio's scene timeline into AI-video shots: prompts, segments and lip-sync audio.

Each camera shot already planned by the timeline (wide, medium, close-up, who speaks, what everyone
does) becomes one AI shot. Its keyframe comes from the Blender scene at that moment, so staging,
poses and costume colours stay consistent; the text prompt describes the same moment for the
image and video models.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from blender.motion_math import sample_path
from utils.config import FPS

STYLE = ("3D Pixar-style animated movie still, cute stylized cartoon characters with big expressive eyes and "
         "soft rounded features, soft warm cinematic lighting, vibrant colors, highly detailed, family friendly")
NEGATIVE = ("blurry, low quality, distorted face, deformed hands, extra fingers, extra limbs, text, letters, "
            "watermark, logo, photorealistic, scary, gore")

LOCATION_TEXT = {
    "construction_site": "a busy construction site in a sunny Pakistani city, bricks, scaffolding and a yellow crane",
    "city_road": "a colourful city road with buildings, trees and street lights",
    "motorcycle_garage": "a small motorcycle garage with tyres and tools",
    "car_workshop": "a friendly car workshop with a car on a lift and tool racks",
    "house": "outside a cosy family house with a garden fence",
    "school": "in front of a cheerful school building",
    "police_station": "outside a police station",
    "park": "a sunny green park with trees, benches and flowers",
    "hideout": "inside a dim purple warehouse hideout with crates and hanging lamps",
    "shop": "a busy bazaar street with shop awnings",
    "village": "a Punjabi village courtyard with mud-brick houses, a charpai, clay pots and green fields",
}
ACTION_TEXT = {
    "walk": "walking", "run": "running", "fly": "flying through the sky like a superhero",
    "hero_landing": "landing in a superhero pose", "jump": "jumping", "sit": "sitting", "ride": "riding a motorcycle",
    "celebrate": "cheering happily with arms up", "laugh_body": "laughing", "scared_body": "looking scared",
    "talk": "talking", "talk_open": "talking with open friendly gestures", "point": "pointing",
    "threaten": "shaking a fist angrily", "wave": "waving", "clap": "clapping", "hands_on_hips": "standing confidently",
    "work": "working hard", "look_around": "looking around", "power_up": "glowing with superpower energy",
    "surprised": "looking surprised", "scared": "looking scared", "laugh": "laughing",
}
CAMERA_TEXT = {
    "establishing": ("wide establishing shot", "slow push in"), "wide": ("wide shot", "slow push in"),
    "dolly_out": ("wide shot", "slow pull back"), "orbit": ("wide shot", "slow orbit around the characters"),
    "medium": ("medium shot", "subtle push in"), "closeup": ("close-up portrait", "static camera"),
    "extreme_closeup": ("extreme close-up on the face", "static camera"),
    "over_shoulder": ("over-the-shoulder shot", "static camera"), "tracking": ("tracking shot", "camera follows"),
    "low_angle": ("low angle hero shot", "slow tilt up"),
}


@dataclass
class AIShot:
    scene_id: int
    index: int
    start: int
    end: int
    camera: str
    key_frame: int
    image_prompt: str
    motion_prompt: str
    seed: int
    characters: list[str] = field(default_factory=list)
    lipsync: list[dict] = field(default_factory=list)  # [{"audio", "offset_s", "speaker"}] relative to shot start

    @property
    def frames(self) -> int:
        return self.end - self.start


def _appearance(cid: str, spec: dict) -> str:
    name = spec.get("name", cid)
    if spec.get("appearance"):
        return f"{name} ({spec['appearance'].rstrip('.')})"
    return name


def _active(clips: list[dict], f: int) -> list[str]:
    return [c["clip"] for c in clips if c["start"] <= f < c["end"]]


def plan_scene(sd: dict, specs: dict[str, dict], seed_base: int = 1234) -> list[AIShot]:
    chars = {c["id"]: c for c in sd["characters"]}
    shots: list[AIShot] = []
    for i, cam in enumerate(sd["camera_shots"]):
        start, end = int(cam["start"]), int(min(cam["end"], sd["frame_count"]))
        if end <= start:
            continue
        key = start + min(12, max(0, (end - start) // 3))
        visible = [cid for cid, c in chars.items()   # on stage horizontally (flying characters count too)
                   if abs(sample_path(c["path"], key)["x"]) < 8.0 or cid == cam.get("subject")]
        if cam.get("subject") in visible:  # subject first: it is the focus of the shot
            visible.remove(cam["subject"])
            visible.insert(0, cam["subject"])
        speaking = [d for d in sd["dialogues"] if d["start"] < end and d["end"] > start]
        doing = []
        for cid in visible:
            acts = [ACTION_TEXT[a] for a in _active(chars[cid].get("body", []), key) + _active(
                chars[cid].get("gestures", []), key) if a in ACTION_TEXT and a != "idle"]
            name = specs.get(cid, {}).get("name", cid)
            if any(d["speaker"] == cid for d in speaking):
                emo = next(d.get("emotion") or "neutral" for d in speaking if d["speaker"] == cid)
                doing.append(f"{name} is talking with a {emo} expression" + (f" while {acts[-1]}" if acts else ""))
            elif acts:
                doing.append(f"{name} is {acts[-1]}")
        shot_txt, move_txt = CAMERA_TEXT.get(cam["type"], ("medium shot", "static camera"))
        who = "; ".join(_appearance(c, specs.get(c, {})) for c in visible) or "no characters"
        place = LOCATION_TEXT.get(sd.get("location", ""), sd.get("location", "").replace("_", " "))
        image_prompt = f"{STYLE}. {shot_txt} of {place}. Characters: {who}. " + ". ".join(doing)
        motion_prompt = (f"{'. '.join(doing) or 'gentle idle movement, characters breathing and blinking'}. "
                         f"{move_txt}, smooth natural animation, {STYLE}")
        lips = []
        for d in speaking:
            if d["speaker"] in visible and d.get("audio"):
                lips.append({"audio": d["audio"], "offset_s": (d["start"] - start) / FPS, "speaker": d["speaker"]})
        shots.append(AIShot(sd["id"], i, start, end, cam["type"], key, image_prompt.strip(), motion_prompt.strip(),
                            seed_base + sd["id"] * 100 + i, visible, lips))
    return shots


def segments(n_frames: int, clip_frames: int = 121) -> list[int]:
    """Split a shot into model-sized pieces (Wan 2.2 lengths must be 4k+1); last piece is trimmed later."""
    usable = clip_frames - 1
    count = max(1, math.ceil(n_frames / usable))
    return [clip_frames] * count
