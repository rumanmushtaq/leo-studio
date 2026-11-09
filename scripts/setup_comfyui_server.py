"""Prepare a ComfyUI install on the GPU PC for Leo Studio's AI video mode.

Run it with ComfyUI's own Python, pointing at the ComfyUI folder:
    python setup_comfyui_server.py /path/to/ComfyUI            (Linux)
    python_embeded\\python.exe setup_comfyui_server.py ComfyUI  (Windows portable build)

Downloads (about 17 GB, free, from Hugging Face):
  Flux.1-schnell fp8      (Apache-2.0)        -> models/checkpoints
  Wan 2.2 TI2V-5B fp16    (Apache-2.0)        -> models/diffusion_models
  UMT5-XXL fp8 encoder    (Apache-2.0)        -> models/text_encoders
  Wan 2.2 VAE             (Apache-2.0)        -> models/vae
and installs the ComfyUI-LatentSyncWrapper custom node (it fetches LatentSync 1.6 weights,
CreativeML OpenRAIL++-M, on first use). Then start ComfyUI with:  python main.py --listen
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

MODELS = [
    ("Comfy-Org/flux1-schnell", "flux1-schnell-fp8.safetensors", "checkpoints"),
    ("Comfy-Org/Wan_2.2_ComfyUI_Repackaged", "split_files/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors",
     "diffusion_models"),
    ("Comfy-Org/Wan_2.1_ComfyUI_repackaged", "split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors",
     "text_encoders"),
    ("Comfy-Org/Wan_2.2_ComfyUI_Repackaged", "split_files/vae/wan2.2_vae.safetensors", "vae"),
]
LATENTSYNC_REPO = "https://github.com/ShmuelRonen/ComfyUI-LatentSyncWrapper"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    comfy = Path(sys.argv[1]).resolve()
    if not (comfy / "main.py").exists() or not (comfy / "models").is_dir():
        print(f"{comfy} does not look like a ComfyUI folder (main.py and models/ expected)")
        return 1
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "huggingface_hub"])
    from huggingface_hub import hf_hub_download

    for repo, filename, sub in MODELS:
        dest = comfy / "models" / sub / Path(filename).name
        if dest.exists():
            print("ok      ", dest.name)
            continue
        print("download", dest.name, "...")
        path = hf_hub_download(repo, filename, local_dir=comfy / "models" / sub / "_hf")
        Path(path).replace(dest)
    nodes = comfy / "custom_nodes" / "ComfyUI-LatentSyncWrapper"
    if not nodes.exists():
        subprocess.check_call(["git", "clone", "--depth", "1", LATENTSYNC_REPO, str(nodes)])
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "-r", str(nodes / "requirements.txt")])
    print("\nDone. Start ComfyUI with:  python main.py --listen   (then use this PC's IP address in Leo Studio)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
