# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

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
- Native window not yet verified on real Windows and macOS hardware.
