import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from utils.config import find_blender  # noqa: E402

LEO_SCRIPT = (ROOT / "assets" / "scripts" / "leo_episode_001.txt").read_text(encoding="utf-8")


def pytest_configure(config):
    config.addinivalue_line("markers", "blender: needs a Blender 4.x executable")
    config.addinivalue_line("markers", "e2e: full pipeline run (slow, opt-in with LEO_E2E=1)")


@pytest.fixture
def leo_script() -> str:
    return LEO_SCRIPT


@pytest.fixture
def registry(tmp_path):
    from core.character_manager import CharacterRegistry

    return CharacterRegistry(registry_file=tmp_path / "registry.json")


@pytest.fixture
def parsed_leo(leo_script, registry):
    from core.scene_manager import SceneManager
    from core.script_parser import ScriptParser

    p = ScriptParser().parse(leo_script)
    SceneManager(registry).enrich(p)
    return p


requires_blender = pytest.mark.skipif(find_blender() is None, reason="Blender not installed")
