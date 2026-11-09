"""Qt studio window: pages, episode scanning, generation flow (mock), thumbnails, YouTube upload (fake)."""
import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PIL import Image  # noqa: E402
from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.generation_controller import GenerationResult, Progress  # noqa: E402
from models.hardware_detector import HardwareReport  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    from gui_qt import theme

    theme.apply(app)
    return app


@pytest.fixture(autouse=True)
def private_prefs(tmp_path, monkeypatch):
    from utils import user_prefs

    monkeypatch.setattr(user_prefs, "PREFS_FILE", tmp_path / "prefs.json")


def fake_hw() -> HardwareReport:
    return HardwareReport(os_name="TestOS", cpu_model="Test CPU", physical_cores=4, logical_cores=8,
                          ram_total_gb=8.0, ram_available_gb=4.0, blender_path="/bin/true",
                          blender_version="Blender 4.5", ffmpeg_path="/bin/true", recommended_quality="preview")


def make_episode(out_dir, name="test_episode_001", frames=(5, 3), video=False, script=""):
    root = out_dir / name
    scenes, start = [], 0.0
    for i, n in enumerate(frames, start=1):
        d = root / "renders" / f"scene_{i:03d}"
        d.mkdir(parents=True)
        for f in range(n):
            Image.new("RGB", (64, 36), (40 * i, 80, 120)).save(d / f"frame_{f:04d}.jpg")
        scenes.append({"id": i, "title": f"Scene {i}", "location": "park", "frame_count": 5, "duration": 5 / 24,
                       "start_time": start, "characters": [{"id": "leo"}],
                       "dialogues": [{"text": "سلام", "speaker": "leo"}]})
        start += 5 / 24
    (root / "scene_data.json").write_text(json.dumps({"fps": 24, "total_seconds": start, "scenes": scenes}))
    (root / "project.json").write_text(json.dumps({"ok": video}))
    if video:
        (root / "final_cartoon.mp4").write_bytes(b"\0")
    if script:
        proj = out_dir.parent / "projects"
        proj.mkdir(exist_ok=True)
        (proj / f"{name}.leo.json").write_text(json.dumps({"script": script}), encoding="utf-8")
    return root


class FakeWorker(QObject):
    """Stands in for GenerationWorker: reports progress and finishes when started."""

    progress = Signal(object)
    finished_result = Signal(object)
    result_dir = None

    def __init__(self, settings, script):
        super().__init__()
        self.settings, self.script = settings, script

    def start(self):
        self.progress.emit(Progress("render", "Rendering frames (EEVEE)", 50.0, 3, 6, 1, 2, "frame 3"))
        self.finished_result.emit(GenerationResult(ok=True, video=None, episode_dir=FakeWorker.result_dir))

    def cancel(self):
        pass

    def wait(self, _ms=0):
        return True


# ------------------------------------------------------------------ episodes
def test_episode_scan_and_scene_tools(tmp_path):
    from gui_qt.episodes import clear_scene_frames, find_episodes, make_thumbnail, scene_at

    out = tmp_path / "output"
    make_episode(out, script="Scene 1: Park")
    (eps,) = find_episodes(out)
    assert eps.name == "test_episode_001" and eps.script == "Scene 1: Park"
    assert [s.frames_done for s in eps.scenes] == [5, 3]
    assert eps.scenes[0].rendered and not eps.scenes[1].rendered
    assert scene_at(eps, 0.3).id == 2 and scene_at(eps, 0.0).id == 1
    assert make_thumbnail(eps).exists()  # no video: falls back to a rendered frame
    assert clear_scene_frames(eps, 1) == 5
    assert not (eps.root / "renders" / "scene_001").exists()


# -------------------------------------------------------------------- window
@pytest.fixture
def window(qapp, tmp_path):
    from gui_qt.app import StudioWindow
    from gui_qt.state import StudioState

    state = StudioState(hardware=fake_hw(), worker_factory=FakeWorker)
    state.settings.output_dir = tmp_path / "output"
    win = StudioWindow(state)
    yield win
    win.close()


def test_all_pages_build_and_switch(window, qapp):
    from gui_qt.app import PAGES

    for key, _ in PAGES:
        window.go(key)
        qapp.processEvents()
        assert window.stack.currentWidget() is window.pages[key]
        assert window.nav_buttons[key].isChecked()


def test_script_page_checks_script(window, qapp, leo_script):
    page = window.pages["script"]
    window.state.set_script(leo_script)
    page._check()
    assert page.n_scenes.text() == "6"
    assert "Leo" in page.cast_text.text()
    window.state.set_script("not a script")
    page._check()
    assert "fix" in page.status.text().lower() or page.n_scenes.text() == "–"


def test_urdu_lines_are_right_to_left(window, qapp):
    from PySide6.QtCore import Qt

    ed = window.pages["script"].editor
    ed.setPlainText("Leo:\nالسلام علیکم")
    assert ed.document().findBlockByNumber(1).textDirection() == Qt.RightToLeft
    assert ed.document().findBlockByNumber(0).textDirection() == Qt.LeftToRight


def test_generation_flow_updates_render_page_and_opens_episode(window, qapp, tmp_path, leo_script):
    root = make_episode(tmp_path / "output", script=leo_script)
    FakeWorker.result_dir = root
    err = window.state.generate(leo_script)
    assert err is None
    qapp.processEvents()
    render = window.pages["render"]
    assert "ready" in render.stage.text().lower()
    assert render.bar.value() == 1000
    assert window.state.episode and window.state.episode.root == root
    assert not window.state.busy
    assert len(window.pages["storyboard"].cards) == 2


def test_generate_rejects_bad_script(window):
    assert "problem" in window.state.generate("").lower()


def test_rerender_clears_only_that_scene(window, qapp, tmp_path, leo_script, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    root = make_episode(tmp_path / "output", name="ep_rr", script=leo_script)
    FakeWorker.result_dir = root
    window.state.open_episode(root)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    window.pages["storyboard"]._rerender(window.state.episode.scenes[1])
    assert (root / "renders" / "scene_001").exists()
    assert not (root / "renders" / "scene_002").exists()
    assert window.state.settings.episode_name in (None, "ep_rr")


def test_character_save_writes_registry(window, qapp, tmp_path, monkeypatch):
    import gui_qt.pages.characters as cp
    from core.character_manager import CharacterRegistry

    reg_file = tmp_path / "registry.json"
    monkeypatch.setattr(cp, "CharacterRegistry", lambda: CharacterRegistry(registry_file=reg_file))
    page = cp.CharactersPage(window.state, window)
    page.select("leo")
    page.data["height"] = 1.33
    page._save()
    assert json.loads(reg_file.read_text(encoding="utf-8"))["characters"]["leo"]["height"] == 1.33


# --------------------------------------------------------------- thumbnails
def test_thumbnail_maker_urdu_title(tmp_path):
    from engines.thumbnail_maker import SIZE, make_thumbnail

    frame = Image.new("RGB", (640, 360), (90, 140, 200))
    out = make_thumbnail(frame, "لیو اور گمشدہ بکری", tmp_path / "t.jpg")
    img = Image.open(out)
    assert img.size == SIZE
    assert out.stat().st_size < 2_000_000
    # the title area differs from the plain frame
    assert img.crop((300, 560, 980, 700)).getextrema() != Image.new("RGB", (1, 1)).getextrema()


# ------------------------------------------------------------------ YouTube
def test_video_meta_body_and_checks():
    from engines.youtube_uploader import VideoMeta

    m = VideoMeta(title="Leo", tags=["a", "b"])
    body = m.body()
    assert body["status"] == {"privacyStatus": "private", "selfDeclaredMadeForKids": True,
                              "containsSyntheticMedia": True, "embeddable": True}
    assert body["snippet"]["categoryId"] == "1"
    assert VideoMeta(title="x" * 101).problems()
    assert VideoMeta(title="<bad>").problems()
    assert not m.problems()


def test_upload_with_fake_service(tmp_path):
    pytest.importorskip("googleapiclient")
    from engines.youtube_uploader import VideoMeta, upload

    calls = {}

    class Status:
        def progress(self):
            return 0.5

    class InsertRequest:
        def __init__(self):
            self.n = 0

        def next_chunk(self):
            self.n += 1
            return (Status(), None) if self.n == 1 else (None, {"id": "abc123"})

    class Videos:
        def insert(self, part, body, media_body):
            calls["body"] = body
            return InsertRequest()

    class Thumbs:
        def set(self, videoId, media_body):  # noqa: N803 (Google API naming)
            calls["thumb"] = videoId

            class R:
                def execute(self):
                    return {}
            return R()

    class Service:
        def videos(self):
            return Videos()

        def thumbnails(self):
            return Thumbs()

    video = tmp_path / "v.mp4"
    video.write_bytes(b"\0" * 1024)
    thumb = tmp_path / "t.jpg"
    Image.new("RGB", (1280, 720)).save(thumb)
    steps = []
    res = upload(video, VideoMeta(title="Leo"), thumb, lambda f, m: steps.append(f), service=Service())
    assert res["url"] == "https://youtu.be/abc123" and res["thumbnail_set"]
    assert calls["thumb"] == "abc123"
    assert calls["body"]["status"]["privacyStatus"] == "private"
    assert steps[-1] == 1.0
