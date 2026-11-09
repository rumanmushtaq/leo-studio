"""Free CPU AI helpers: story writer (llama.cpp + Qwen3), background painter, time estimates."""
import pytest

from engines.background_painter import BackgroundPainter
from engines.script_writer import ScriptWriter, WriterError
from tests.conftest import LEO_SCRIPT
from utils import user_prefs

BAD = "Once upon a time Leo saved a goat. The end."


class FakeWriter(ScriptWriter):
    """ScriptWriter with the llama.cpp server replaced by canned answers."""

    def __init__(self, answers):
        super().__init__()
        self.answers = list(answers)
        self.proc = object()   # pretend the server is running
        self.seen = []

    def _chat(self, messages, max_tokens=1800):
        self.seen.append(messages)
        return self.answers.pop(0)


def test_writer_retries_until_script_parses():
    w = FakeWriter([BAD, "```\n**Scene 1: Park**\n" + LEO_SCRIPT + "\n```"])
    script = w.write("Leo helps", "ur")
    assert script.startswith("Scene 1: Park") and "**" not in script and "```" not in script
    assert len(w.seen) == 2
    assert "Fix these problems" in w.seen[1][-1]["content"]      # parser feedback was sent back


def test_writer_gives_clear_error():
    with pytest.raises(WriterError, match="could not produce"):
        FakeWriter([BAD, BAD, BAD]).write("x", "en")


def test_writer_prompt_mentions_format_and_cast():
    msgs = ScriptWriter.prompt("Leo saves a goat", "ur")
    system = msgs[0]["content"]
    assert "Scene 1:" in system and "Visual:" in system and "Leo" in system and "village" in system
    assert "Urdu" in system and "Leo saves a goat" in msgs[1]["content"]


def test_problems_on_good_script():
    assert ScriptWriter.problems(LEO_SCRIPT) == []


def test_background_cache_path():
    p = BackgroundPainter.cached_path("village", 7)
    assert p.name == "village_7.png" and p.parent.name == "backgrounds"


def test_time_estimate_scales_with_quality(tmp_path, monkeypatch):
    monkeypatch.setattr(user_prefs, "PREFS_FILE", tmp_path / "p.json")
    quick = user_prefs.estimate_minutes(120, "preview")
    best = user_prefs.estimate_minutes(120, "standard")
    assert quick < best
    user_prefs.record_render_speed("preview", 2.0)              # this PC turned out slower
    assert user_prefs.estimate_minutes(120, "preview") > quick
    assert "hour" in user_prefs.human_duration(130) and "minutes" in user_prefs.human_duration(40)
