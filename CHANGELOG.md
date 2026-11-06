# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `scripts/check_a11y.py`: audits every screen in both themes (axe-core WCAG 2.1 AA rules when given `axe.min.js`,
  40 px targets, keyboard Tab walk with visible focus, no horizontal scroll at 200 % zoom).
- Subtle motion (transform/opacity only): views fade in, score bars grow, the selected-row marker slides in.

### Changed
- Every control has a hit area of at least 40 px; compact buttons keep their look.
- Progress is announced to screen readers once per stage or 10 % instead of on every update.
- The results list is an ARIA grid (fixes nested interactive controls); keyboard shortcuts in the editor have AA contrast.
- Narrow windows and 200 % zoom: results stack above the preview, the top bar stays on one line, timeline labels no
  longer overlap.
- The projects list renders 50 rows at a time as you scroll (400 projects: ~550 ms → ~130–250 ms to open, measured
  in headless Chromium).
- With "reduce motion", pulsing and sliding indicators are static.

## [0.2.0] - 2026-11-05

"Editor" release.

### Added
- Canvas timeline in the clip editor: waveform computed by the server for the visible range, draggable in/out
  handles that snap to sentence boundaries (Alt for free movement), click/drag scrubbing, zoom (Ctrl+wheel, buttons).
- Word-level transcript synced with playback: the spoken word is highlighted, click a word to jump to it,
  double-click to fix it.
- "See real frame": one frame rendered by the export engine (same reframe and libass subtitles) for the current,
  even unsaved, edit.
- Keyboard shortcuts (Space, ←/→, Shift+←/→, I/O, Ctrl/Cmd+Z, Ctrl/Cmd+Shift+Z, Ctrl/Cmd+Enter), undo/redo
  history and autosave with a status indicator.
- Projects screen (search, rename, delete, show exported folder) and "Continue where you left off" on Home.
- Full settings: output folder, export quality (CRF 24/20/17), hardware encoder and loudness options, speech model
  management (download, default, delete) and disk usage with "Free up space" (caches only).

### Changed
- Exports default to the folder chosen in Settings (still overridable with `SNIPSCOUT_OUTPUT_DIR`).

## [0.1.0] - 2026-11-05

First public version ("it works").

### Added
- Local pipeline: probe (ffprobe or PyAV), 16 kHz audio extraction, resumable chunked transcription with
  faster-whisper (Fast / Balanced / Accurate models, pinned and SHA-256 verified downloads with pause/resume),
  sentence segmentation with prosody features.
- Explainable clip selection without any language model: seven weighted signals, sentence-boundary candidates,
  diversity (MMR), extractive titles, hooks and keywords; top 3 pre-selected.
- Rendering: 9:16 / 1:1 / 16:9 / original with center crop or blurred background, word-by-word highlighted
  subtitles (Pop, Classic, Karaoke, Minimal) burned in with libass, `.srt` / `.vtt`, `metadata.json`, captions text.
- Desktop app: local server on 127.0.0.1 with a session token, native window (pywebview) with automatic browser
  fallback, first-run setup, drag-and-drop or file picker, live processing view, results with preview and reasons,
  simple clip editor, export screen with per-clip progress, ZIP and "show in folder".
- Spanish and English interface, light and dark themes, WCAG AA contrast checked in CI.
- `snipscout run` and `snipscout doctor` commands; `SNIPSCOUT_OFFLINE=1` blocks any network access.
- Launchers: `Start-SnipScout.bat` (Windows, double-click), `start-snipscout.sh` / `Start-SnipScout.command`.

### Known limitations
- Clip selection tuned on synthetic transcripts only.
- Windows launcher verified on a real machine; native window on macOS not yet verified.
