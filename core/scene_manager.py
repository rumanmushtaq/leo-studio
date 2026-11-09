"""Semantic enrichment of parsed scenes.

Adds environment type, characters present, per-character animation actions,
dialogue emotions, camera hints, sound effect ids and duration estimates.
Rules are keyword based (English + Urdu) so they work offline on any story.
"""
from __future__ import annotations

import re

from core.character_manager import CharacterRegistry
from core.script_parser import Event, ParsedScene, ParsedScript

LOCATIONS: dict[str, list[str]] = {
    "construction_site": ["construction", "building site", "site", "crane", "brick", "cement", "wall",
                          "تعمیر", "تعمیراتی", "دیوار", "اینٹ", "سیمنٹ", "مزدور"],
    "motorcycle_garage": ["motorcycle garage", "bike shop", "bike garage", "garage",
                          "موٹر سائیکل", "گیراج"],
    "car_workshop": ["workshop", "mechanic", "car repair", "repair shop", "ورکشاپ", "مستری", "مکینک"],
    "city_road": ["road", "street", "highway", "traffic", "biker", "bike", "سڑک", "گلی", "بائیک", "ٹریفک"],
    "school": ["school", "classroom", "سکول", "اسکول", "کلاس"],
    "house": ["house", "home", "room", "گھر", "کمرہ"],
    "police_station": ["police station", "police", "headquarters", "agency", "تھانہ", "پولیس"],
    "park": ["park", "garden", "playground", "happy ending", "celebrat", "پارک", "باغ", "میدان", "جشن"],
    "hideout": ["hideout", "lair", "den", "warehouse", "secret base", "اڈہ", "ٹھکانہ", "گودام"],
    "village": ["village", "gaon", "farm", "courtyard", "buffalo", "گاؤں", "دیہات", "گاوں", "کھیت", "حویلی", "भैंस", "गांव"],
    "shop": ["shop", "market", "bazaar", "store", "دکان", "بازار"],
}

ACTION_RULES: list[tuple[str, str]] = [
    (r"\bfl(y|ies|ying|ew)\b.*\b(in|into|down|toward|onto)\b|\bfrom the sky\b|اڑتا ہوا آ|آسمان سے|اڑ کر آ", "fly_in"),
    (r"\b(takes off|flies away|flies off|flies up)\b|اڑ گیا|اڑ جاتا", "fly_out"),
    (r"\bland(s|ing|ed)?\b|اترتا|اتر", "hero_landing"),
    (r"\b(shield)\b|ڈھال", "energy_shield"),
    (r"\b(power|glow|blast|beam)\b|\benergy\b(?! shield)|طاقت|روشنی", "power_up"),
    (r"\b(run|runs|ran|running) (away|off)\b|\bflee|بھاگ", "run_away"),
    (r"\b(rides?|riding)\b|موٹر سائیکل چلا|بائیک چلا", "ride_in"),
    (r"\b(walks?|walking|enters?|arrives?|comes?)\b(?!.*\bsky\b)|آتا|آتے|آتی|داخل", "walk_in"),
    (r"\b(leaves?|exits?|walks away|goes away)\b|چلا جاتا|چلے جاتے", "walk_out"),
    (r"\b(jumps?|jumping|hops?)\b|چھلانگ|اچھل", "jump"),
    (r"\b(sits?|sitting|seated)\b|بیٹھ", "sit"),
    (r"\b(waves?|waving)\b|ہاتھ ہلا", "wave"),
    (r"\b(points?|pointing)\b|اشارہ", "point"),
    (r"\b(claps?|clapping|applaud)\b|تالی", "clap"),
    (r"\b(laughs?|laughing|giggles?)\b|ہنس|قہقہ", "laugh"),
    (r"\b(threaten|threatening|bully|bullying|demands?|grabs?)\b|دھمکی|دھمکا|تنگ", "threaten"),
    (r"\b(looks? around|searching)\b|ادھر ادھر", "look_around"),
    (r"\b(works?|working|hammer|builds?|building|repairs?|repairing|fixing)\b|کام کر|مرمت", "work"),
    (r"\b(celebrates?|celebrating|cheers?|cheering|dance|dancing)\b|خوشی|جشن|ناچ", "celebrate"),
    (r"\b(scared|afraid|frightened|trembl)\w*|(?<![\u0600-\u06FF])ڈر(?![\u0600-\u06FF])|ڈر گئ|خوفزدہ", "scared"),
    (r"\b(turns?|turning)\b|(?<![\u0600-\u06FF])مڑ", "turn"),
]

EMOTIONS = ["neutral", "happy", "sad", "angry", "surprised", "scared", "confident", "laughing"]
EMOTION_ALIASES = {
    "excited": "happy", "joyful": "happy", "cheerful": "happy", "smiling": "happy", "خوش": "happy",
    "upset": "sad", "crying": "sad", "اداس": "sad", "furious": "angry", "mad": "angry", "غصہ": "angry",
    "shocked": "surprised", "amazed": "surprised", "حیران": "surprised", "afraid": "scared",
    "frightened": "scared", "worried": "scared", "ڈرا": "scared", "proud": "confident", "brave": "confident",
    "laughs": "laughing", "giggling": "laughing", "threatening": "angry", "menacing": "angry",
}
EMOTION_RULES: list[tuple[str, str]] = [
    (r"ہا\s?ہا|ہی\s?ہی|\bha\s?ha|\bhehe|\blol\b", "laughing"),
    (r"بچاؤ|مدد کرو|ڈر لگ|بھاگو|\bhelp me\b|\bscared\b|\bafraid\b|\brun\b!|please don.t", "scared"),
    (r"پیسے دو|خبردار|ورنہ|\bgive (me|us)\b|\bor else\b|\bhow dare\b", "angry"),
    (r"کیا\?|کیا؟|(?<![\u0600-\u06FF])ارے(?![\u0600-\u06FF])|واقعی\?|واقعی؟|\bwhat\?|\bwow\b|\bwhoa\b|\breally\?", "surprised"),
    (r"شکریہ|واہ|زبردست|بہت خوب|مزہ|خوش|\bthank|\byay\b|\bgreat\b|\bawesome\b", "happy"),
    (r"افسوس|اداس|رو رہ|\bsorry\b|\bsad\b", "sad"),
    (r"میں ہوں|محافظ|فکر نہ|فکر مت|\bdon.t worry\b|\bi am\b|\bi.m here\b|\bprotect", "confident"),
]

SFX_RULES: list[tuple[str, str]] = [
    (r"siren|پولیس کی گاڑی|سائرن", "police_siren"),
    (r"motorcycle|motorbike|bike engine|موٹر سائیکل|بائیک", "motorcycle"),
    (r"\bcar\b|horn|traffic|engine|گاڑی|ہارن", "car"),
    (r"whoosh|fly|wind|ہوا|اڑ", "flying"),
    (r"magic|power|sparkle|energy|طاقت|جادو", "magic"),
    (r"shield|ڈھال", "shield"),
    (r"footstep|steps|walk|قدم", "footsteps"),
    (r"crowd|people|cheer|applause|ہجوم|لوگ|تالیاں", "crowd"),
    (r"hammer|clank|construction|drill|ہتھوڑ|تعمیر", "construction"),
    (r"wrench|workshop|tools|اوزار|ورکشاپ", "workshop"),
    (r"land|thud|boom|دھماک", "landing"),
    (r"hero|entrance|ta-da|fanfare|ہیرو", "hero_entrance"),
    (r"laugh|ہنس", "crowd"),
]

CAMERA_RULES: list[tuple[str, str]] = [
    (r"extreme close", "extreme_closeup"), (r"close", "closeup"), (r"over.the.shoulder|ots", "over_shoulder"),
    (r"establish|wide|long shot", "wide"), (r"medium", "medium"), (r"track|follow", "tracking"),
    (r"dolly in|push in|zoom in", "dolly_in"), (r"dolly out|pull out|zoom out", "dolly_out"),
    (r"orbit|circle|around", "orbit"), (r"pan", "pan"), (r"tilt", "tilt"),
]

ACTION_SECONDS = {
    "fly_in": 3.5, "fly_out": 2.5, "hero_landing": 1.5, "energy_shield": 2.5, "power_up": 2.0,
    "run_away": 2.5, "ride_in": 3.5, "walk_in": 3.0, "walk_out": 3.0, "jump": 1.2, "sit": 1.5,
    "wave": 1.5, "point": 1.2, "clap": 1.5, "laugh": 1.8, "threaten": 1.8, "look_around": 2.0,
    "work": 2.5, "celebrate": 2.5, "scared": 1.5, "turn": 1.0,
}


def location_for(text: str) -> str | None:
    low = text.lower()
    best, best_pos = None, None
    for loc, words in LOCATIONS.items():
        for w in words:
            pos = low.find(w)
            if pos >= 0 and (best_pos is None or pos < best_pos):
                best, best_pos = loc, pos
    return best


def infer_emotion(event: Event, role: str) -> str:
    hint = (event.emotion_hint or "").strip().lower()
    if hint:
        if hint in EMOTIONS:
            return hint
        if hint in EMOTION_ALIASES:
            return EMOTION_ALIASES[hint]
    low = event.text.lower()
    for pattern, emo in EMOTION_RULES:
        if re.search(pattern, low):
            return emo
    if role == "villain" and re.search(r"[!！]", event.text):
        return "angry"
    if re.search(r"[!！]", event.text):
        return "happy"
    if re.search(r"[?؟]", event.text):
        return "surprised"
    return "neutral"


def sfx_for(text: str) -> str | None:
    low = text.lower()
    for pattern, sid in SFX_RULES:
        if re.search(pattern, low):
            return sid
    return None


class SceneManager:
    """Turns a :class:`ParsedScript` into fully annotated scenes."""

    def __init__(self, registry: CharacterRegistry):
        self.registry = registry

    def enrich(self, script: ParsedScript) -> ParsedScript:
        scenes = script.scenes
        if len(scenes) == 1 and scenes[0].inferred:
            scenes = self._split_inferred(scenes[0])
            script.scenes = scenes

        # Speakers first, so group words ('bullies') resolve to known characters.
        speaker_ids: list[str] = []
        for s in scenes:
            for e in s.events:
                if e.kind == "dialogue":
                    spec = self.registry.get_or_create(e.speaker or "", context=e.text)
                    e.speaker_id = spec.id
                    if spec.id not in speaker_ids:
                        speaker_ids.append(spec.id)
        visual_text = " ".join(e.text for s in scenes for e in s.events if e.kind == "visual")
        for cid in self.registry.mentions(visual_text):
            if cid not in speaker_ids and cid != "narrator":
                spec = self.registry.get_or_create(cid)
                if not spec.voice_only:
                    speaker_ids.append(cid)

        prev_location = None
        for s in scenes:
            self._enrich_scene(s, speaker_ids, prev_location)
            prev_location = s.location
            if not s.characters:
                script.report.warnings.append(
                    f"Scene {s.id} has no on-screen characters; it will show the environment only.")
        return script

    def _split_inferred(self, scene: ParsedScene) -> list[ParsedScene]:
        """Split a heading-less script into scenes at location changes."""
        out: list[ParsedScene] = []
        cur = ParsedScene(id=1, title="", inferred=True)
        cur_loc = None
        dialogue_count = 0
        for e in scene.events:
            loc = location_for(e.text) if e.kind in ("visual", "location") else None
            new_place = loc is not None and cur_loc is not None and loc != cur_loc and dialogue_count > 0
            too_long = e.kind == "visual" and dialogue_count >= 10
            if (new_place or too_long) and cur.events:
                out.append(cur)
                cur = ParsedScene(id=len(out) + 1, title="", inferred=True)
                dialogue_count = 0
            if loc:
                cur_loc = loc
            if e.kind in ("dialogue", "narration"):
                dialogue_count += 1
            cur.events.append(e)
        if cur.events:
            out.append(cur)
        return out

    def _enrich_scene(self, s: ParsedScene, known: list[str], prev_location: str | None) -> None:
        visuals = [e for e in s.events if e.kind in ("visual", "location")]
        s.visual_description = " ".join(e.text for e in visuals).strip()
        loc_text = " ".join([s.title] + [e.text for e in s.events if e.kind == "location"])
        s.location = (location_for(loc_text) or location_for(s.visual_description)
                      or prev_location or "city_road")
        if not s.title:
            s.title = s.location.replace("_", " ").title()

        present: list[str] = []
        for e in s.events:
            if e.kind == "dialogue" and e.speaker_id and e.speaker_id not in present:
                if not self.registry.get_or_create(e.speaker_id).voice_only:
                    present.append(e.speaker_id)
            if e.kind in ("visual", "location"):
                for cid in self.registry.mentions(e.text, known):
                    if cid not in present and cid != "narrator":
                        present.append(cid)
        s.characters = present

        for e in s.events:
            if e.kind == "visual":
                e.actions = self._actions(e.text, present, known)
            elif e.kind in ("dialogue", "narration"):
                role = self.registry.get_or_create(e.speaker_id or "narrator").role
                e.emotion = infer_emotion(e, role)
            elif e.kind == "camera":
                for pattern, shot in CAMERA_RULES:
                    if re.search(pattern, e.text.lower()):
                        s.camera_hints.append(shot)
                        e.actions = [{"camera": shot, "subjects": self.registry.mentions(e.text, present)}]
                        break
            elif e.kind == "sfx":
                sid = sfx_for(e.text)
                e.actions = [{"sfx": sid or "whoosh", "matched": sid is not None}]
                s.sound_effects.append(sid or "whoosh")
            elif e.kind == "transition":
                low = e.text.lower()
                s.transition_in = "fadeblack" if ("black" in low or "fade" in low) else "dissolve"
            # Visual lines may also imply sounds (sirens, engines) even without an SFX label.
            if e.kind == "visual":
                sid = sfx_for(e.text)
                if sid in ("police_siren", "motorcycle", "car", "crowd"):
                    s.sound_effects.append(sid)

        s.estimated_duration = round(self.estimate_duration(s), 2)

    def _actions(self, text: str, present: list[str], known: list[str]) -> list[dict]:
        """Per-character actions from a visual description, sentence by sentence.

        The subject of an action is the character(s) named *before* the verb
        ("Boss points at Karim" -> boss), falling back to the previous
        sentence's subject, or to everyone for "everyone/all/سب".
        """
        actions: list[dict] = []
        sentences = re.split(r"[.!?؟۔;]|\band then\b|\bthen\b|\bwhile\b", text)
        last_subjects: list[str] = []
        locomotion = {"fly_in", "walk_in", "run_away", "ride_in", "walk_out", "fly_out"}

        def add(cid: str, action: str) -> None:
            if not any(a["character"] == cid and a["action"] == action for a in actions):
                actions.append({"character": cid, "action": action})

        for sentence in sentences:
            if not sentence.strip():
                continue
            mentions = [(p, c) for p, c in self.registry.mentions_with_pos(sentence, known) if c != "narrator"]
            everyone = re.search(r"\b(everyone|everybody|all of them|together)\b|سب", sentence, re.I)
            moved: set[str] = set()
            for pattern, action in ACTION_RULES:
                m = re.search(pattern, sentence, re.I)
                if not m:
                    continue
                before = [c for p, c in mentions if p < m.start()]
                after = [c for p, c in mentions if p >= m.start()]
                subjects = before or (present if everyone else last_subjects) or after[:1]
                if not subjects:
                    continue
                last_subjects = subjects
                for cid in subjects:
                    if action in locomotion:
                        if cid in moved:
                            continue
                        moved.add(cid)
                    add(cid, action)
                    if action == "fly_in":
                        add(cid, "hero_landing")
        return actions

    @staticmethod
    def estimate_duration(s: ParsedScene) -> float:
        total = 2.5  # establishing shot
        for e in s.events:
            if e.kind in ("dialogue", "narration"):
                words = len(e.text.split())
                total += max(1.4, words / (2.3 if e.language == "ur" else 2.6)) + 0.4
            elif e.kind == "visual":
                total += max([ACTION_SECONDS.get(a["action"], 0) for a in e.actions] or [1.0])
        return total + 1.0
