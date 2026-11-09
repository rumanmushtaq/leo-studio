"""Render every page of the Qt studio offscreen to PNG files (for review and docs).

Usage: QT_QPA_PLATFORM=offscreen python scripts/ui_screenshots.py OUT_DIR
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication  # noqa: E402

from gui_qt import theme  # noqa: E402
from gui_qt.app import PAGES, StudioWindow  # noqa: E402


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/screenshots")
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    theme.apply(app)
    win = StudioWindow()
    win.resize(1440, 900)
    win.show()
    for _ in range(20):
        app.processEvents()
    if win.state.episode is None:
        from gui_qt.episodes import find_episodes

        eps = find_episodes(win.state.settings.output_dir)
        if eps:
            win.state.open_episode(eps[0].root)
    for key, _ in PAGES:
        win.go(key)
        for _ in range(30):
            app.processEvents()
        win.grab().save(str(out / f"{key}.png"))
        print("saved", out / f"{key}.png")
    win.go("home")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
