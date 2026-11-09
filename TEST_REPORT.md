# Test report

Machine: Intel i5-10210U, 8 GB RAM, Intel UHD iGPU, Ubuntu 24.04, Blender 4.5.15 LTS, Python 3.11.16.

## Automated suite

```
.venv/bin/python -m pytest -q tests                      -> 42 passed, 1 skipped (e2e is opt-in) in 4 min 22 s
LEO_E2E=1 LEO_E2E_QUALITY=standard LEO_E2E_OUT=output \
LEO_E2E_NAME=leo_episode_001 python -m pytest tests/test_e2e.py   -> 1 passed in 8 min (frames reused)
```

| File | Covers |
|---|---|
| `tests/test_script_parser.py` | 6 Leo scenes + locations, all 19 Urdu lines kept verbatim, narration vs dialogue, characters per scene, subject-before-verb actions, emotions, SFX, empty-script error, heading-less scene inference, Urdu speaker labels, unlabeled text kept |
| `tests/test_characters.py` | aliases (incl. Urdu), deterministic procedural designs, Leo preset matches the brief, registry persistence and asset reuse hash, group mentions |
| `tests/test_motion_timeline.py` | quaternion maths, yaw convention, **walk feet planted** (stance foot speed == body speed), gesture masking, every clip evaluates, no overlapping/cut dialogue, 60 s extension without duplicating lines, camera shots cover every frame, entrances start off-stage / in the sky, only the speaker lip-syncs, village keywords |
| `tests/test_audio_subtitles.py` | real Urdu speech from eSpeak NG + cache, manual audio import, loud failure without audio, amplitude lip-sync, all procedural SFX + music, mixer ducking/stereo/limiting, SRT verbatim, **Urdu shaping** (HarfBuzz/raqm joins letters) and RTL subtitle image |
| `tests/test_blender.py` | builds Leo/Karim/bullies in Blender: bones, leg IK, 6 face shape keys, outline, CC0 base body re-skinned to our rig, scene file animated with camera markers (tracking, low-angle), effects, same Karim asset in two scenes, rendered frame not blank |
| `tests/test_video_assembly.py` | FFmpeg scene encode + cross-fade + Urdu subtitle overlay + AAC → H.264 1280×720 24 fps, frame count, A/V sync, clean decode, validator rejects < 60 s |
| `tests/test_e2e.py` | complete Leo episode through the real pipeline and all checks below |

## Leo sample episode — `output/leo_episode_001/final_cartoon.mp4`

| Check | Result |
|---|---|
| Video stream / codec | ✅ H.264, yuv420p |
| Audio stream / codec | ✅ AAC 192 kb/s, 44.1 kHz stereo |
| Resolution / frame rate | ✅ 1280×720, 24 fps |
| Duration ≥ 60 s | ✅ 129.63 s |
| Frame count | ✅ 3,111 (= timeline) |
| Audio vs video duration | ✅ 129.63 s / 129.63 s |
| Full decode, no errors | ✅ |
| OpenCV frame scan (missing / unreadable / blank) | ✅ 0 / 0 / 0 across 6 scenes |
| All scenes rendered | ✅ 6 scenes: 632, 392, 561, 472, 570, 544 frames |
| All dialogue accounted (timeline + SRT) | ✅ 19 / 19 lines |
| Camera shots used | establishing, wide, orbit, medium, close-up, tracking, low-angle hero shot, dolly-out (over-the-shoulder is implemented but the planner did not pick it in this episode) |
| Voices | eSpeak NG (Hugging Face returned HTTP 429, MMS model not downloadable from this network) |
| Render engine | EEVEE (Intel iGPU), standard quality |

Visual spot checks of frames extracted from the MP4 (`docs/final_frames_1.jpg`, `docs/final_frames_2.jpg`):
Urdu subtitles render as joined Nastaliq, right-to-left, with speaker tags; talking characters open their
mouths, listeners turn their heads; Leo flies in from the sky and lands; Bilal rides in on the motorcycle;
the energy shield appears in the hideout; the park ending shows the three friends.

Known visual defects seen in the sample: Motu's forearms sink into his scaled-up belly; costume edges
are painted (no cloth); eSpeak voices are robotic.
