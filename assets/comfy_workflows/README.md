# AI video mode (ComfyUI)

Leo Studio can hand the picture-making to a **ComfyUI** server running on a PC with an NVIDIA GPU
(the same PC or another one on your network). Everything else — script, characters, staging,
voices, music, Urdu subtitles, timing, final MP4 — stays in the studio.

## Pipeline per camera shot
1. **Blender layout keyframe** of the shot (same characters, poses, costume colours as the 3D mode).
2. **Flux.1-schnell img2img** (`restyle_flux.json`) repaints it in a Pixar-like style.
3. **Wan 2.2 TI2V-5B image-to-video** (`image_to_video_wan22.json`) animates it, 121 frames (~5 s)
   per piece; longer shots chain pieces from the last frame.
4. **LatentSync** (`lipsync_latentsync.json`) lip-syncs pieces where a visible character speaks.
5. Pieces are cut/padded to the shot's exact frames; scenes keep the planned length, so audio and
   subtitles stay in sync.
All results are cached (`<episode>/ai_work/cache`), so an interrupted run resumes.

## GPU PC setup
| | Minimum | Recommended |
|---|---|---|
| GPU | NVIDIA 12 GB (slow, may need lower resolution) | 16–24 GB (RTX 4060 Ti 16 GB, 3090, 4090) |
| RAM / disk | 32 GB / 40 GB free | 64 GB / 100 GB |

1. Install ComfyUI (Windows: portable zip from the ComfyUI GitHub releases; Linux: git clone + pip).
2. Copy `scripts/setup_comfyui_server.py` to that PC and run it with ComfyUI's Python:
   `python setup_comfyui_server.py /path/to/ComfyUI` (downloads ~17 GB of free models, installs LatentSync node).
3. Start ComfyUI with `python main.py --listen` and allow port 8188 in the firewall.
4. In Leo Studio: **Advanced… → Render engine → AI video (ComfyUI server)**, enter
   `http://<gpu-pc-ip>:8188`, press **Test connection**. CLI: `--engine ai --comfy http://<ip>:8188`.

Rough speed on an RTX 4090: 2–6 min per 5-second piece; a 2-minute episode ≈ 1–2.5 hours.

## Licences
| Model | Licence | Commercial use |
|---|---|---|
| Flux.1-schnell | Apache-2.0 | yes |
| Wan 2.2 TI2V-5B, UMT5 encoder, Wan VAE | Apache-2.0 | yes |
| LatentSync 1.6 | code Apache-2.0, weights CreativeML OpenRAIL++-M | yes, with the licence's use restrictions |
| ComfyUI | GPL-3.0 | yes (software you run, outputs are yours) |

## Changing models
The JSON files are ComfyUI **API-format** workflows with `{{PLACEHOLDER}}` values filled by the studio
(`{{IMAGE}}`, `{{PROMPT}}`, `{{NEGATIVE}}`, `{{SEED}}`, `{{WIDTH}}`, `{{HEIGHT}}`, `{{FRAMES}}`, `{{FPS}}`,
`{{STEPS}}`, `{{DENOISE}}`, `{{VIDEO}}`, `{{AUDIO}}`). Export your own workflow from ComfyUI with
"Save (API)", put the placeholders in, keep the file name — the studio checks that every node type
exists on the server before running and names any missing custom node.

## Limits
- Not run against a real GPU server during development (no NVIDIA GPU available); the studio side is
  tested against a mock ComfyUI server (`tests/test_ai_video.py`) that speaks the same API.
- Generated video can drift slightly from the character design between shots, and hands can be
  imperfect; check episodes before publishing.
- Readable text inside generated images is not reliable — Urdu subtitles are overlaid by the studio.
