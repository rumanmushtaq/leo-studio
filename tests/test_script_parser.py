"""Script parsing, scene extraction and semantic enrichment."""
import re

from core.scene_manager import SceneManager
from core.script_parser import ScriptParser, detect_language


def test_leo_scenes_extracted(parsed_leo):
    titles = [s.title for s in parsed_leo.scenes]
    assert titles == ["Construction Site", "Leo's Entry", "City Road", "Car Workshop", "Bullies' Hideout",
                      "Happy Ending in the Park"]
    assert [s.location for s in parsed_leo.scenes] == ["construction_site", "construction_site", "city_road",
                                                       "car_workshop", "hideout", "park"]
    assert parsed_leo.report.ok and not parsed_leo.report.errors


def test_all_dialogue_kept_verbatim(leo_script, parsed_leo):
    # every line that follows a speaker label in the source must appear unchanged
    source_lines = [l.strip() for l in leo_script.splitlines() if re.search(r"[؀-ۿ]", l)]
    parsed_lines = [e.text for e in parsed_leo.all_dialogue_events()]
    assert parsed_lines == source_lines
    assert len(parsed_lines) == 19


def test_speakers_and_narration(parsed_leo):
    s1 = parsed_leo.scenes[0]
    kinds = [(e.kind, e.speaker_id) for e in s1.dialogues]
    assert kinds == [("narration", "narrator"), ("dialogue", "karim"), ("dialogue", "boss"), ("dialogue", "karim")]


def test_characters_per_scene(parsed_leo):
    assert set(parsed_leo.scenes[0].characters) == {"karim", "boss", "chintu", "motu"}
    assert "leo" in parsed_leo.scenes[1].characters
    assert set(parsed_leo.scenes[4].characters) >= {"leo", "karim", "bilal", "ustad_akram", "boss", "chintu", "motu"}
    assert "narrator" not in {c for s in parsed_leo.scenes for c in s.characters}


def test_actions_assigned_to_subject_not_object(parsed_leo):
    acts = {(a["character"], a["action"]) for e in parsed_leo.scenes[0].events if e.kind == "visual" for a in e.actions}
    assert ("boss", "point") in acts and ("karim", "point") not in acts
    assert ("karim", "work") in acts
    acts2 = {(a["character"], a["action"]) for e in parsed_leo.scenes[1].events if e.kind == "visual" for a in e.actions}
    assert ("leo", "fly_in") in acts2 and ("leo", "hero_landing") in acts2
    assert not any(c != "leo" and a == "fly_in" for c, a in acts2)


def test_emotions(parsed_leo):
    emo = {(e.speaker_id, e.text[:6]): e.emotion for e in parsed_leo.all_dialogue_events()}
    by_speaker = [(e.speaker_id, e.emotion) for e in parsed_leo.all_dialogue_events()]
    assert ("boss", "angry") in by_speaker
    assert ("karim", "scared") in by_speaker          # explicit (scared)
    assert ("chintu", "surprised") in by_speaker
    assert ("leo", "laughing") in by_speaker
    assert ("motu", "scared") in by_speaker           # "بھاگو!"
    assert emo


def test_sfx_and_durations(parsed_leo):
    assert "hero_entrance" in parsed_leo.scenes[1].sound_effects
    assert all(s.estimated_duration > 5 for s in parsed_leo.scenes)


def test_empty_script_reports_error():
    p = ScriptParser().parse("   ")
    assert not p.report.ok


def test_no_headings_infers_scenes(registry):
    text = ("Visual: Karim works at the construction site.\nKarim: آج کام ختم ہوگا۔\n"
            "Visual: Bilal rides on the road.\nBilal: سڑک صاف ہے۔\n")
    p = ScriptParser().parse(text)
    SceneManager(registry).enrich(p)
    assert len(p.scenes) == 2
    assert [s.location for s in p.scenes] == ["construction_site", "city_road"]
    assert any("inferred" in w for w in p.report.warnings)


def test_urdu_speaker_labels_resolve(registry):
    p = ScriptParser().parse("سین 1: پارک\nلیو: سلام!\nکریم: وعلیکم السلام۔\n")
    SceneManager(registry).enrich(p)
    assert [e.speaker_id for e in p.all_dialogue_events()] == ["leo", "karim"]
    assert p.scenes[0].location == "park"


def test_unlabeled_lines_are_kept(registry):
    p = ScriptParser().parse("Scene 1: Park\nThe sun is shining.\nLeo: Hello!\n")
    assert p.scenes[0].events[0].kind == "visual"
    assert p.report.warnings


def test_language_detection():
    assert detect_language("میں ہوں لیو!") == "ur"
    assert detect_language("I am Leo!") == "en"
