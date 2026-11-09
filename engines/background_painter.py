"""AI-painted scene backgrounds on the CPU (free, offline after one download).

Model: Intel's OpenVINO int8 build of LCM-Dreamshaper-v7 (MIT-tagged repository; based on
Stable Diffusion 1.5 / Dreamshaper, CreativeML OpenRAIL-M terms), 2.3 GB, run with
OpenVINO + optimum-intel in 4 LCM steps - a few tens of seconds per image on a laptop CPU.

Each location gets one painted, people-free backdrop, cached in ``assets/backgrounds/`` and
reused by every episode, so places look the same across a series. The 3D characters,
ground and props stay in Blender in front of it.
"""
from __future__ import annotations

import gc
import os
from pathlib import Path
from typing import Callable

from PIL import Image, ImageFilter

from utils.config import ASSETS_DIR, MODEL_CACHE
from utils.logger import get_logger

log = get_logger("backgrounds")

REPO = "OpenVINO/LCM_Dreamshaper_v7-int8-ov"
REVISION = "340a03e5488f36f7f222e6efa29819850ad7e4be"
DOWNLOAD_MB = 2300
MODEL_DIR = MODEL_CACHE / "lcm_dreamshaper_v7_int8_ov"
BACKGROUND_DIR = ASSETS_DIR / "backgrounds"
# Measured: loading + compiling the int8 pipeline peaks above 3.2 GB of RAM (OOM-killed under a 3.2 GB cap
# on an 8 GB laptop). Below this much free memory the painter is skipped. Override: LEO_PAINTER_MIN_MB
MIN_FREE_MB = int(os.environ.get("LEO_PAINTER_MIN_MB", "4000"))

STYLE = ("Pixar style 3D animated movie background, empty scene with no people, wide angle, "
         "soft warm sunlight, vibrant colors, highly detailed, beautiful matte painting")
NEGATIVE = "people, person, character, face, animal, text, letters, watermark, logo, blurry, dark, ugly"
PLACES = {
    "construction_site": "a sunny construction site in a Pakistani city, half-built brick building, scaffolding, "
                         "yellow crane, sand and bricks",
    "city_road": "a colourful city street with shops and houses, trees and street lights, blue sky",
    "motorcycle_garage": "a small roadside motorcycle repair garage with tyres and tools, city houses behind",
    "car_workshop": "a friendly car repair workshop with an open garage door, tools on the wall",
    "house": "a cosy colourful family house with a garden and a fence",
    "school": "a cheerful school building with a playground and trees",
    "police_station": "a small friendly police station building on a quiet street",
    "park": "a sunny green park with big trees, flowers and benches, blue sky with clouds",
    "hideout": "inside a big dim warehouse with purple light, wooden crates and hanging lamps",
    "shop": "a busy colourful bazaar street with shop awnings and stalls",
    "village": "a Punjabi village with mud brick houses, green crop fields, trees and a dirt path, blue sky",
}


class BackgroundPainter:
    def __init__(self):
        self._pipe = None

    @staticmethod
    def available() -> bool:
        """Packages installed? (checked without importing them: optimum pulls in torch, ~15 s)."""
        from importlib.util import find_spec

        try:
            return find_spec("openvino") is not None and find_spec("optimum.intel") is not None
        except (ImportError, ValueError):
            return False

    @staticmethod
    def is_installed() -> bool:
        return (MODEL_DIR / "model_index.json").exists() and (MODEL_DIR / "unet" / "openvino_model.bin").exists()

    @staticmethod
    def install(progress: Callable[[float, str], None] | None = None) -> None:
        from huggingface_hub import snapshot_download

        if progress:
            progress(0.0, f"Downloading the background painter (about {DOWNLOAD_MB / 1000:.1f} GB)…")
        snapshot_download(REPO, revision=REVISION, local_dir=MODEL_DIR)
        if progress:
            progress(1.0, "Background painter ready")

    @staticmethod
    def cached_path(location: str, seed: int) -> Path:
        return BACKGROUND_DIR / f"{location}_{seed}.png"

    @staticmethod
    def free_mb() -> int:
        import psutil

        return int(psutil.virtual_memory().available / 2**20)

    def _load(self, width: int, height: int):
        if self._pipe is None:
            if self.free_mb() < MIN_FREE_MB:
                raise MemoryError(f"only {self.free_mb()} MB of free memory; the painter needs {MIN_FREE_MB} MB "
                                  "(close other programs)")
            from optimum.intel import OVLatentConsistencyModelPipeline

            # The repository ships a 1.2 GB fp32 PyTorch safety checker; the prompts are the studio's own
            # place descriptions, so it is not loaded. A static shape compiles smaller, faster graphs.
            pipe = OVLatentConsistencyModelPipeline.from_pretrained(str(MODEL_DIR), compile=False,
                                                                    safety_checker=None)
            pipe.reshape(batch_size=1, height=height, width=width, num_images_per_prompt=1)
            pipe.compile()
            self._pipe = pipe
        return self._pipe

    def paint(self, location: str, seed: int = 7, width: int = 768, height: int = 432) -> Path:
        out = self.cached_path(location, seed)
        if out.exists():
            return out
        import torch

        pipe = self._load(width, height)
        prompt = f"{STYLE}, {PLACES.get(location, location.replace('_', ' '))}"
        gen = torch.Generator().manual_seed(seed)
        img = pipe(prompt=prompt, negative_prompt=NEGATIVE, num_inference_steps=4, guidance_scale=8.0,
                   width=width, height=height, generator=gen).images[0]
        # upscale for the 72 m backdrop; a touch of blur reads as distance / depth of field
        img = img.resize((2048, 1152), Image.LANCZOS).filter(ImageFilter.GaussianBlur(1.2))
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out)
        log.info("Painted background for %s -> %s", location, out.name)
        return out

    def paint_all(self, locations: list[str], progress: Callable[[int, int, str], None] | None = None,
                  seed: int = 7) -> dict[str, str]:
        out: dict[str, str] = {}
        unique = list(dict.fromkeys(locations))
        try:
            for k, loc in enumerate(unique, start=1):
                out[loc] = str(self.paint(loc, seed))
                if progress:
                    progress(k, len(unique), loc)
        finally:
            self.close()
        return out

    def close(self) -> None:
        self._pipe = None
        gc.collect()
