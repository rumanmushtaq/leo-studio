# Hardware, model/license report and known limitations

## 1. Hardware compatibility (measured on the development machine)

| Item | Value |
|---|---|
| OS | Ubuntu 24.04.5 LTS, kernel 7.0 |
| CPU | Intel Core i5-10210U, 4 cores / 8 threads |
| RAM | 8 GB (about 1.8–2.6 GB free during development) |
| GPU | Intel UHD Graphics (CometLake-U GT2), no NVIDIA GPU, no CUDA |
| Blender | 4.5.15 LTS (portable tarball, `~/opt`) |
| FFmpeg | 7.0.2 static build; `ffprobe` absent → validator uses its `ffmpeg -i` fallback |
| Python | 3.11.16 (uv-managed, includes Tk 9.0 without Xft) |

What runs where:

* **EEVEE** (default renderer) runs on the integrated Intel GPU through Mesa/OpenGL in Blender's
  background mode — verified. EEVEE always needs *some* OpenGL 4.3 GPU/iGPU; it is not a pure-CPU
  renderer. On a machine with no GPU context the render manager falls back to **Workbench**
  (still real 3D geometry and lighting, simpler shading) and records the fallback in `project.json`.
  **Cycles** (CPU or CUDA/OptiX) is used only for quality "high" with the GPU option switched on.
* Everything else (parsing, TTS, lip-sync, audio, subtitles, FFmpeg) is CPU-only.
* Memory: one Blender process at a time; peak about 1.5 GB during the first EEVEE frame
  (shader compilation), about 150–300 MB while rendering. Frames are written one by one to JPEG;
  nothing keeps the video in RAM. Torch + MMS-TTS add about 0.5 GB while voices are generated
  and are unloaded afterwards.

Measured speed (Leo episode, 6 scenes, low-poly assets):

| Step | Measured |
|---|---|
| Build one character asset (base body import, re-proportion, rig, head, costume, reference render) | 45–60 s each, one Blender process per character (peak RAM ≈ 1 GB) |
| Build one scene .blend (environment, append characters, bake animation, camera) | 10–15 s |
| Render, *standard* (1280×720, 4 EEVEE samples, shadows, AO, DoF) | ≈ 2.4 s per frame on the Intel UHD iGPU |
| Render, *preview* (640×360, 1 sample) | ≈ 0.5 s per frame (measured on an earlier asset build) |
| Leo episode, standard, end to end | 3,111 frames / 129.6 s of video in 2 h 35 min (9,277 s) |
| Disk per episode | rendered JPEG frames ≈ 300 MB, final MP4 ≈ 27 MB |

Quality presets: *preview* = 640×360 render, 1 EEVEE sample, no shadows, upscaled to 1280×720 in
the MP4; *standard* = native 1280×720, 4 samples, shadows; *high* = 16 samples (or Cycles + GPU).
Real-time rendering is not possible on this class of laptop; a 2-minute episode takes tens of
minutes (preview) to a few hours (standard).

### Windows / Linux support

| Item | Linux | Windows 10/11 |
|---|---|---|
| Install | `install_linux.sh` (run and verified on Ubuntu 24.04) | `install_windows.ps1` (written for Windows; **not executed here**, no Windows machine available) |
| Blender | PATH, `tools/`, `~/opt/`, portable download | PATH, Program Files, `tools/`, portable zip download (SHA-256 checked) |
| FFmpeg | system `ffmpeg` or `imageio-ffmpeg` wheel | `imageio-ffmpeg` wheel, winget/choco paths |
| Urdu subtitles | libraqm: Nastaliq | reshaper + bidi fallback: Naskh (tested on Linux with raqm disabled) |
| Child processes | UTF-8 decoding | UTF-8 decoding, no console windows (`CREATE_NO_WINDOW`) |
| Hardware detection | `/proc/cpuinfo`, `lspci`, `nvidia-smi` | registry CPU name, PowerShell `Get-CimInstance` GPUs (works without `wmic`), `nvidia-smi` |
| Open video/folder | `xdg-open` | `os.startfile` |

Windows behaviour was verified on Linux by tests that simulate it (`tests/test_cross_platform.py`):
no libraqm, no system FFmpeg, PowerShell GPU query, Program Files Blender lookup. A real run on a
Windows PC is still recommended before relying on it.

## 2. Models and licenses

| Component | Use | License | Notes |
|---|---|---|---|
| Blender 4.5 LTS | 3D modelling, rigging, animation, rendering | GPL-2.0-or-later | Output files belong to the user. |
| FFmpeg | Encoding, transitions, subtitle overlay, muxing | LGPL-2.1+/GPL (build dependent; static build is GPL-3.0) | |
| Meta MMS-TTS Urdu `facebook/mms-tts-urd-script_arabic` | Urdu speech (VITS) | **CC-BY-NC-4.0** | Non-commercial only. ~145 MB, CPU inference. |
| Meta MMS-TTS English `facebook/mms-tts-eng` | English lines | **CC-BY-NC-4.0** | Non-commercial only. |
| eSpeak NG (via `espeakng-loader` wheel) | Fallback Urdu/English TTS | GPL-3.0 (wrapper MIT) | Fully offline, robotic voice. |
| Piper TTS | investigated | MIT (engine) | No Urdu voice in the official Piper voice list at the time of writing → not integrated. |
| Stable Fast 3D (`stabilityai/stable-fast-3d`) | investigated for image-to-3D characters | Stability AI Community License (free below USD 1M annual revenue; check current terms) | Needs a CUDA GPU (~6 GB VRAM) and produces single static meshes without rigs → not integrated; procedural Blender modelling is used. |
| Qwen3-4B-Instruct-2507 (Q4_K_M GGUF, unsloth build) | story-idea → script writer (CPU) | Apache-2.0 | 2.5 GB, SHA-256 pinned, optional. |
| llama.cpp `llama-server` b12211 (CPU builds) | runs the writer model | MIT | ~25 MB, SHA-256 pinned, downloaded from the official GitHub release. |
| OpenVINO/LCM_Dreamshaper_v7-int8-ov | painted scene backgrounds (CPU) | model card: MIT; derived from Stable Diffusion 1.5 (CreativeML OpenRAIL-M use restrictions apply) | 2.3 GB, revision pinned, optional. |
| OpenVINO 2024.6, optimum-intel 1.21, diffusers 0.31 | run the background model | Apache-2.0 | |
| PyTorch 2.5.1 (CPU) | MMS inference | BSD-3-Clause | |
| Transformers 4.46.3 | MMS loading | Apache-2.0 | |
| PySide6 6.8.1 (Qt 6) | studio window, video player | LGPL-3.0 (Qt for Python) | Installed from PyPI as a shared library; not modified. |
| CustomTkinter 5.2.2 | classic window (`--classic`) | MIT | |
| google-api-python-client 2.154 / google-auth-oauthlib 1.2.1 | optional YouTube upload | Apache-2.0 | Uses the owner's own Google OAuth client; token in `tokens/`. |
| Pillow 11.3 (+ libraqm, HarfBuzz, FriBiDi) | Urdu shaping, subtitles | MIT-CMU (HPND); libraqm MIT | |
| NumPy 1.26.4 | audio synthesis/mixing | BSD-3-Clause | |
| OpenCV 4.10 (headless) | frame quality checks | Apache-2.0 | |
| soundfile / libsndfile | WAV I/O | BSD-3 / LGPL-2.1 | |
| pydub 0.25.1 | MP3/M4A import for manual audio | MIT | |
| psutil | hardware detection | BSD-3-Clause | |
| Noto Nastaliq Urdu / Noto Naskh Arabic / Noto Sans | subtitles, preview | SIL OFL 1.1 | Bundled in `assets/fonts/` with `LICENSE_Noto_fonts.txt`. |
| imageio-ffmpeg | bundled FFmpeg binary | BSD-2-Clause (wrapper); FFmpeg binary LGPL/GPL | Used only when no system FFmpeg is found. |
| arabic-reshaper / python-bidi | Urdu shaping fallback | MIT / LGPL-3.0 | Used when Pillow lacks libraqm (typical on Windows). |
| Sound effects and music | all audio except speech | Original, generated by `engines/sound_engine.py` (released by this project as CC0) | No third-party samples or copyrighted music. User WAVs in `assets/sounds/` / `assets/music/` override them — the user is responsible for their licenses. |
| Quaternius *Universal Base Characters* (Standard, free tier) | base body meshes and skin weights | **CC0 1.0** (public domain; `assets/characters/base/quaternius_ubc/License_Standard.txt`) | Downloaded from the official itch.io page; only the two glTF bodies are vendored (1.7 MB). Credit appreciated: "Models by Quaternius". |
| Cartoon heads, faces, costumes, accessories, environments, props | all other 3D assets | Original, generated by the Blender scripts in this repository | |

Important: with the default MMS voices the generated videos are for **non-commercial use**
(CC-BY-NC-4.0 of the voice model). For commercial work use eSpeak NG (`--voice espeak`) or
your own recordings (`--voice manual`).

## 3. Known limitations

1. **Voices.** MMS-TTS is a single-speaker model; characters differ by controlled pitch/tempo, not by
   true speaker identity. Hugging Face rate-limited this network (HTTP 429) for most of development;
   once it allowed the download, the sample episode was re-rendered with the MMS Urdu voice. If the model
   cannot be downloaded the app falls back to eSpeak NG (robotic) and records that in `project.json`.
2. **Lip-sync** is amplitude based with a spectral vowel-colour heuristic (open / wide / round). It
   is not phoneme-accurate; no offline Urdu phoneme aligner is bundled.
3. **Character look.** Bodies come from a professionally modelled CC0 base (good anatomy, five-finger
   hands); heads, faces and costumes are generated. Costumes are painted onto the body plus shell
   accessories, so there is no real cloth (no folds, no loose kurta/shalwar fabric) and no hair or cloth
   simulation (the cape is bone-animated). The result is stylised TV/game quality, not Pixar-film quality:
   no free CC0 Pixar-style rigged characters exist, and AI image/video generators that produce that look
   need cloud services or a large NVIDIA GPU.
4. **Script understanding** is rule based (English + Urdu keywords). Unusual phrasing may map to a
   generic action or location; every guess is visible in `parsed_script.json`, and nothing the user
   wrote is dropped. Pure-Urdu stage directions are recognised only for the keywords in
   `core/scene_manager.py`.
5. **Environment variety** is limited to ten procedural location types; unknown places fall back to
   the previous scene's location or a city road.
6. **Render time** on an i5 laptop iGPU is long (see table above); there is no distributed or
   real-time rendering.
7. **Studio window.** The Qt window shapes Urdu natively. On Linux/X11 it needs `libxcb-cursor0`; without
   it the classic Tk window opens, which on uv/standalone Python builds uses bitmap fonts and cannot
   shape Urdu in its edit box (use its *Urdu preview* tab). The Windows build of the Qt window has not
   been run on a real Windows PC here.
8. **YouTube upload** needs a one-time Google Cloud OAuth client created by the channel owner. Unverified
   Google projects run in "testing" mode (sign-in tokens expire after 7 days, then the app asks to sign in
   again). Custom thumbnails need a phone-verified channel; the video still uploads without one.
9. `ffprobe` was not available on the development machine; verification used the built-in
   `ffmpeg -i` fallback parser plus a full decode pass. Installing `ffmpeg` from apt provides
   `ffprobe`, which the validator then uses automatically.
