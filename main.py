"""Leo 3D AI Cartoon Studio — entry point.

    python main.py                      # desktop studio (Qt); --classic for the older window
    python main.py --check              # hardware + dependency report
    python main.py --cli SCRIPT.txt [--out DIR] [--quality preview|standard|high]
                   [--voice auto|mms|espeak|manual] [--manual-audio DIR] [--name EPISODE]
"""
from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

REQUIRED = [("numpy", "numpy"), ("PIL", "pillow"), ("soundfile", "soundfile"), ("psutil", "psutil"),
            ("cv2", "opencv-python-headless"), ("pydub", "pydub")]
GUI_REQUIRED = [("PySide6", "PySide6")]
CLASSIC_GUI_REQUIRED = [("tkinter", "python3-tk (system package) or a Python build with Tk"),
                        ("customtkinter", "customtkinter")]


def check_dependencies(gui: bool, classic: bool = False) -> list[str]:
    missing = []
    for mod, pkg in REQUIRED + ((CLASSIC_GUI_REQUIRED if classic else GUI_REQUIRED) if gui else []):
        try:
            importlib.import_module(mod)
        except ImportError:
            missing.append(f"{mod} (install: {pkg})")
    return missing


def _qt_display_missing() -> bool:
    """Qt 6 on Linux/X11 needs libxcb-cursor; without it Qt aborts instead of raising, so check first."""
    import os
    import platform

    if platform.system() != "Linux" or os.environ.get("WAYLAND_DISPLAY") or os.environ.get("QT_QPA_PLATFORM"):
        return False
    from ctypes.util import find_library

    if find_library("xcb-cursor"):
        return False
    print("The studio window needs the system library libxcb-cursor0: sudo apt install libxcb-cursor0\n"
          "Starting the classic window for now.")
    return True


def main() -> int:
    # Windows consoles default to a legacy code page; Urdu names/paths must not crash printing.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Leo 3D AI Cartoon Studio")
    ap.add_argument("--check", action="store_true", help="print hardware and dependency report")
    ap.add_argument("--cli", metavar="SCRIPT", help="generate from a script file without the GUI")
    ap.add_argument("--idea", metavar="TEXT", help="write a script from a one-line story idea (free local AI), "
                                                   "then generate the video")
    ap.add_argument("--lang", default="ur", choices=["ur", "en"], help="dialogue language for --idea")
    ap.add_argument("--out", default=None)
    ap.add_argument("--quality", default="standard", choices=["preview", "standard", "high"])
    ap.add_argument("--voice", default="auto", choices=["auto", "mms", "espeak", "manual"])
    ap.add_argument("--manual-audio", default=None)
    ap.add_argument("--name", default=None)
    ap.add_argument("--no-music", action="store_true")
    ap.add_argument("--engine", default="blender", choices=["blender", "ai"],
                    help="blender = 3D render on this PC; ai = ComfyUI server (Flux + Wan 2.2 + LatentSync)")
    ap.add_argument("--comfy", default="http://127.0.0.1:8188", help="ComfyUI server address for --engine ai")
    ap.add_argument("--classic", action="store_true", help="start the older, simpler window (CustomTkinter)")
    args = ap.parse_args()

    gui = not (args.check or args.cli or args.idea)
    classic = args.classic
    missing = check_dependencies(gui, classic)
    if gui and not classic and missing and not check_dependencies(gui, classic=True):
        print("PySide6 is not installed; starting the classic window. (pip install -r requirements.txt)")
        classic, missing = True, []
    if missing:
        print("Missing dependencies:\n  " + "\n  ".join(missing))
        print("Run: pip install -r requirements.txt   (see README for system packages)")
        return 2

    from models.hardware_detector import detect

    if args.check:
        rep = detect(check_torch=True)
        print("\n".join(rep.summary_lines()))
        for w in rep.warnings:
            print("WARNING:", w)
        from models.model_manager import model_status

        for m in model_status():
            print(f"Model {m['key']}: {'ready' if m['downloaded'] else 'not downloaded'} | {m['license']} | "
                  f"{m['size_mb']} MB | {'integrated' if m['integrated'] else 'not integrated'}")
        return 0 if not rep.warnings or rep.blender_path else 1

    if args.idea and not args.cli:
        from engines.script_writer import DOWNLOAD_MB, ScriptWriter

        w = ScriptWriter()
        if not w.is_installed():
            print(f"Downloading the free AI story writer (one time, about {DOWNLOAD_MB / 1000:.1f} GB)...")
            w.install(lambda f, m: print(f"\r{m}", end="", flush=True))
            print()
        script = w.write(args.idea, args.lang, progress=lambda f, m: print(m, flush=True))
        from utils.config import PROJECT_ROOT

        out = PROJECT_ROOT / "projects" / "idea_script.txt"
        out.parent.mkdir(exist_ok=True)
        out.write_text(script, encoding="utf-8")
        print(f"Script written: {out}\n")
        args.cli = str(out)

    if args.cli:
        from core.generation_controller import GenerationController
        from utils.config import OUTPUT_DIR, GenerationSettings

        st = GenerationSettings(output_dir=Path(args.out) if args.out else OUTPUT_DIR, quality=args.quality,
                                episode_name=args.name, voice_backend=args.voice,
                                manual_audio_dir=Path(args.manual_audio) if args.manual_audio else None,
                                music=not args.no_music, render_engine=args.engine, comfy_url=args.comfy)
        last = {"stage": None, "pct": -5.0}

        def progress(p):
            if p.stage != last["stage"] or p.percent - last["pct"] >= 1.0:
                last.update(stage=p.stage, pct=p.percent)
                scene = f" [scene {p.scene}/{p.scene_count}]" if p.scene else ""
                print(f"{p.percent:5.1f}%  {p.label}{scene}  {p.message}", flush=True)

        res = GenerationController(st, progress).run(Path(args.cli).read_text(encoding="utf-8"))
        if res.ok:
            print(f"\nSUCCESS: {res.video}")
            return 0
        print(f"\nFAILED: {res.error}")
        return 1

    if not classic and _qt_display_missing():
        classic = True
    if not classic:
        try:
            from gui_qt.app import run_app as run_qt

            return run_qt()
        except ImportError as exc:  # broken Qt install: the classic window still works
            print(f"The new studio window could not start ({exc}); starting the classic window.")
    from gui.app import run_app

    run_app()
    return 0


if __name__ == "__main__":
    sys.exit(main())
