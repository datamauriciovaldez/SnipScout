# PROGRESS

## Done
- **H0** spike: all 6 GO (6 = weak evidence). Details: docs/spike-report.md.
- **H1** skeleton: pyproject (hatchling, uv, ruff/mypy strict/pytest), `core/binaries.py` (env → system → imageio-ffmpeg, real libass+libx264 render probe, cached), typed errors, `config.py` (platformdirs, `CLIPFORGE_OFFLINE` flag), `clipforge doctor [--json] [--no-cache]`, autonomy guard (test + CI), CI matrix ubuntu/windows/macos. 15 tests green.

- **H2** core data: `models.py` (MediaInfo, Transcript, Project, JobEvent…), `storage.py` (atomic JSON, id validation vs path traversal), `ingest.py` (ffprobe or PyAV; rotation, VFR, multi-track, cover-art skip), `audio.py` (16 kHz mono WAV, track select, limit, RMS), `procs.py` (ffmpeg progress + CancelToken), `net.py` (CLIPFORGE_OFFLINE socket guard, loopback allowed). 42 tests green; media fixtures use paths with spaces/accents/emoji.

## Decisions
- Author approved: Whisper `base` default (Rápido=tiny, Preciso=small); embeddings optional download, TF-IDF default.
- ffmpeg probe cache: `<cache>/ffmpeg_probe.json`, keyed by path+size+mtime; only successes cached.
- CLI uses argparse (no extra dependency).
- CI not yet run on GitHub (no remote). Windows/macOS behaviour unverified until first push.

## Next
- **H3**: transcribe (model download w/ progress, benchmark, resumable, quick analysis) + segment.
- Author: create empty public GitHub repo and share `owner/repo` so work can be pushed (container is ephemeral).
