"""Application logging: console plus optional per-episode log file."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def get_logger(name: str) -> logging.Logger:
    root = logging.getLogger("leo")
    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(_FORMAT, "%H:%M:%S"))
        root.addHandler(handler)
        root.setLevel(logging.INFO)
    return root.getChild(name)


def add_file_handler(log_path: Path) -> logging.Handler:
    """Attach a file handler to the app logger; caller removes it when done."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter(_FORMAT))
    logging.getLogger("leo").addHandler(handler)
    return handler


def remove_handler(handler: logging.Handler) -> None:
    logging.getLogger("leo").removeHandler(handler)
    handler.close()
