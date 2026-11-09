# Qt studio UI — design

Date: 2026-11-09. Status: approved by the owner ("Approve, build it").

## Goal

Replace the plain CustomTkinter window with a professional, dark "video editor" style studio that a
non-technical person can use, on Windows and Linux, on a CPU-only laptop. The rendering engine
(`core/`, `engines/`, `blender/`) is not changed except where a page needs a small hook.

## Decisions

| Topic | Decision |
|---|---|
| Toolkit | PySide6 6.8.1 (Qt 6, LGPL-3.0, pip wheels for Windows/Linux/macOS). Qt shapes Urdu (HarfBuzz) and handles right-to-left text natively, so the editor shows real Nastaliq/Naskh. |
| Video | `QMediaPlayer` + `QVideoWidget` (Qt Multimedia, FFmpeg backend bundled in the wheel). |
| Fallback | `main.py` starts `gui_qt`; if PySide6 cannot be imported or Qt cannot open a window, it starts the old `gui` (CustomTkinter) app. |
| Threads | One `QThread` worker per long job (generation, AI writer, downloads, character preview). Workers talk to the UI only through Qt signals. Only one heavy job at a time (8 GB RAM laptops). |
| Style | One QSS theme (`gui_qt/theme.py`), dark navy background, blue accent, rounded cards, Noto fonts bundled in `assets/fonts/` registered with `QFontDatabase`. |

## Window layout

* Left: icon sidebar (Home, Script, Storyboard, Characters, Render, Publish, Settings).
* Top bar: current project name, a status line, and the primary **Make cartoon** button.
* Centre: `QStackedWidget` with one page per sidebar entry.
* Bottom-right toast for short messages; system notification + taskbar alert when a video is ready.

## Pages

1. **Home** — "New cartoon" card (one-line idea or full script, Urdu/English, Quick/Best, time
   estimate, Make button); example ideas as chips; gallery of past episodes found in the output folder
   (thumbnail = a frame from the middle of the video or the first rendered frame, title, length, date)
   with Watch, Open (loads script into editor) and Folder actions.
2. **Script** — `QPlainTextEdit` with a highlighter (scene titles, `Visual:`, speaker labels, emotions),
   Urdu lines aligned right; right panel with live parse results (scenes, characters, line count,
   estimated length, warnings/errors, debounced 600 ms); toolbar: Open, Save project, Leo sample,
   **AI write from idea**. The AI writer result opens a review dialog (Looks good / Edit / Write again).
3. **Storyboard** — for the open episode: one card per scene (thumbnail, location, characters, length,
   first line). Video player with play/pause, seek bar, time, and scene markers; clicking a card seeks
   to that scene. **Re-render scene N** deletes that scene's rendered frames and regenerates the episode;
   unchanged scenes are reused by the existing frame-signature guard, so only scene N is rendered.
4. **Characters** — grid of cards with the reference render; detail panel with colour swatches
   (`QColorDialog`), height/build/belly sliders, 3D-model import, keep-head checkbox, reset, save. Same
   data rules as `gui/characters.py` (registry.json, presets).
5. **Render** — step tracker (12 stages), big progress bar, scene X/Y, ETA (elapsed / fraction), live
   preview of the newest rendered frame (refreshed every 2 s), collapsible log, Cancel.
6. **Publish** — title, description, tags (prefilled from the script), thumbnail maker (pick a frame with a slider, title text with Urdu shaping, export
   1280×720 JPEG), privacy (private default), made-for-kids flag, "altered or synthetic content" flag,
   upload with progress. YouTube Data API v3 with the owner's own OAuth client JSON; token stored in
   `user_settings.json`'s folder (`tokens/youtube.json`), never in the repo. A guide explains the one-time
   Google Cloud setup.
7. **Settings** — voice engine, manual audio folder, music, output folder, render engine / ComfyUI URL
   with test, AI tools status with download buttons, hardware summary.

## Units

```
gui_qt/
  app.py          MainWindow, sidebar, top bar, page switching, run_app()
  theme.py        colours, fonts, style sheet;  icons.py  line icons (SVG)
  state.py        StudioState: settings, current script, current episode dir, signals
  workers.py      GenerationWorker, WriterWorker, CallableWorker (QThread + signals)
  episodes.py     find past episodes, thumbnails, scene ranges (no Qt imports; unit-tested)
  widgets.py      Card, Chip, StepTracker, ThumbCard, Toast, FlowLayout, VideoPlayer
  pages/home.py script.py storyboard.py characters.py render.py publish.py settings.py
engines/youtube_uploader.py   OAuth + resumable upload (no Qt; unit-tested with a fake service)
engines/thumbnail_maker.py    frame + shaped title text -> JPEG (Pillow)
```

## Error handling

* Every worker catches exceptions and emits `failed(str)`; pages show the message in a dialog or
  inline, never crash the window.
* Missing optional parts (writer, painter, Google libraries, YouTube client file) disable only their
  buttons, with a short explanation.
* Cancel sets the controller's cancel event; partial frames are kept (existing resume behaviour).

## Testing

* `tests/test_qt_ui.py` with `QT_QPA_PLATFORM=offscreen`: build every page, switch pages, parse panel
  updates, a mock generation worker drives the Render page and finishes on Home, storyboard cards from
  a fake episode folder, character save writes the registry (temp copy), thumbnail maker output size.
* `engines/youtube_uploader` tested with a fake `googleapiclient` service (request body: privacy,
  `selfDeclaredMadeForKids`, `containsSyntheticMedia`).
* Screenshots of every page (offscreen grab) for the owner's review.

## Build order

1. Shell, theme, state, workers; Home, Script, Render, Settings, Characters pages; launcher switch.
2. Storyboard + video player + scene re-render.
3. Publish page, thumbnail maker, YouTube uploader.
