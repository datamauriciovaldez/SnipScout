# PROGRESS

## Done
- **H0** spike: all 6 GO (6 = weak evidence). Details: docs/spike-report.md.
- **H1** skeleton: pyproject (hatchling, uv, ruff/mypy strict/pytest), `core/binaries.py` (env → system → imageio-ffmpeg, real libass+libx264 render probe, cached), typed errors, `config.py` (platformdirs, `CLIPFORGE_OFFLINE` flag), `clipforge doctor [--json] [--no-cache]`, autonomy guard (test + CI), CI matrix ubuntu/windows/macos. 15 tests green.

## Decisions
- Author approved: Whisper `base` default (Rápido=tiny, Preciso=small); embeddings optional download, TF-IDF default.
- ffmpeg probe cache: `<cache>/ffmpeg_probe.json`, keyed by path+size+mtime; only successes cached.
- CLI uses argparse (no extra dependency).
- CI not yet run on GitHub (no remote). Windows/macOS behaviour unverified until first push.

## Next
- **H2**: models, storage, ingest (ffprobe or PyAV), extract_audio, `CLIPFORGE_OFFLINE` enforcement, tests with synthetic video.
- Author: create empty public GitHub repo and share `owner/repo` so work can be pushed (container is ephemeral).
