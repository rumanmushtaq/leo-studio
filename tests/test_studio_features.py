"""Project files, character editing/import bookkeeping and safe frame reuse."""
import json

from core.character_manager import CharacterRegistry
from core.generation_controller import GenerationController
from core.project_manager import ProjectManager
from utils.config import GenerationSettings


def test_project_file_roundtrip(tmp_path, monkeypatch):
    import utils.config as cfg

    monkeypatch.setattr(cfg, "PROJECT_ROOT", tmp_path)
    st = GenerationSettings(output_dir=tmp_path / "out", quality="preview", voice_backend="espeak")
    p = ProjectManager.save_project("my_ep", "Scene 1: Park\nLeo: سلام!", st)
    data = json.loads(p.read_text(encoding="utf-8"))
    assert p.parent.name == "projects" and data["script"].endswith("سلام!")
    assert data["settings"]["quality"] == "preview" and data["settings"]["voice_backend"] == "espeak"


def test_edited_character_survives_reload(tmp_path):
    reg = CharacterRegistry(registry_file=tmp_path / "r.json")
    data = dict(reg.get_or_create("leo").data)
    data["costume"] = dict(data["costume"], shirt=[0.1, 0.8, 0.2])
    old_hash = reg.characters["leo"].design_hash()
    reg.import_character("leo", data)
    again = CharacterRegistry(registry_file=tmp_path / "r.json")
    assert again.characters["leo"].data["costume"]["shirt"] == [0.1, 0.8, 0.2]   # edit not overridden by preset
    assert again.characters["leo"].design_hash() != old_hash                       # -> asset gets rebuilt


def test_imported_model_spec_changes_hash(tmp_path):
    reg = CharacterRegistry(registry_file=tmp_path / "r.json")
    spec = reg.get_or_create("Zara", "a girl")
    h = spec.design_hash()
    reg.import_character(spec.id, dict(spec.data, model_file="/models/zara.glb", keep_head=True))
    assert reg.characters[spec.id].design_hash() != h


def test_frames_reused_only_for_identical_scene(tmp_path):
    ctrl = GenerationController(GenerationSettings(output_dir=tmp_path, quality="standard"))
    asset = tmp_path / "leo.blend"
    asset.write_bytes(b"x")
    frames = tmp_path / "scene_001"
    sd = {"id": 1, "frame_count": 3, "characters": [{"id": "leo"}], "dialogues": [{"start": 10, "end": 40}]}
    ctrl._guard_frames(frames, sd, {"leo": str(asset)})
    for i in range(3):
        (frames / f"frame_{i:04d}.jpg").write_bytes(b"jpg")
    ctrl._guard_frames(frames, sd, {"leo": str(asset)})                  # unchanged scene -> resume
    assert len(list(frames.glob("frame_*.jpg"))) == 3
    changed = dict(sd, dialogues=[{"start": 10, "end": 52}])            # e.g. new voice timing
    ctrl._guard_frames(frames, changed, {"leo": str(asset)})
    assert not list(frames.glob("frame_*.jpg"))
