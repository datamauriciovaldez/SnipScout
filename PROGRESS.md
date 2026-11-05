# PROGRESS

## Done
- **H0** spike: all 6 GO (6 = weak evidence). Details: docs/spike-report.md.
- **H1** skeleton: pyproject (hatchling, uv, ruff/mypy strict/pytest), `core/binaries.py` (env → system → imageio-ffmpeg, real libass+libx264 render probe, cached), typed errors, `config.py` (platformdirs, `SNIPSCOUT_OFFLINE` flag), `snipscout doctor [--json] [--no-cache]`, autonomy guard (test + CI), CI matrix ubuntu/windows/macos. 15 tests green.

- **H2** core data: `models.py` (MediaInfo, Transcript, Project, JobEvent…), `storage.py` (atomic JSON, id validation vs path traversal), `ingest.py` (ffprobe or PyAV; rotation, VFR, multi-track, cover-art skip), `audio.py` (16 kHz mono WAV, track select, limit, RMS), `procs.py` (ffmpeg progress + CancelToken), `net.py` (SNIPSCOUT_OFFLINE socket guard, loopback allowed). 42 tests green; media fixtures use paths with spaces/accents/emoji.
- **H3** `modelstore.py` (pinned HF revisions + sha256, own HTTP client: byte progress, pause/resume via Range, cancel, offline refusal), `transcribe.py` (5-min chunks with boundary-segment redo, resumable from `processed_until`, quick analysis 10 min, live text + ETA events, RTF stats in `<cache>/speed.json`, bundled 10 s benchmark `assets/benchmark_es.wav`, GPU optional w/ CPU fallback), `segment.py` (punctuation/0.6 s pause/40 words, wps, pauses, confidence, RMS dynamics, fillers), lexicons `core/text/data/{es,en}.json`. 60 tests + 1 slow (real tiny) green.
- **H4** selection: `candidates.py` (sentence-boundary windows, cheap shortlist), `scoring/heuristic.py` (7 signals hook/pace/energy/cohesion/closure/autonomy/confidence → 0-100 + reason keys), `scoring/weights.toml` (single documented tuning file), `refine.py` (padding without touching neighbours, MMR diversity, no overlaps), `text/extract.py` (extractive hook/title), TF-IDF keywords, `select.py` entry point, lexicons es/en, optional `[embeddings]` extra (fastembed). `scripts/eval_scoring.py` + 2 synthetic annotated talks: recall@5 = 7/7 with TF-IDF and with embeddings (synthetic → weak evidence). 72 tests green.
- **H5** output: `subtitles.py` (ASS one event per word, 3-5 word lines, no orphans, presets classic/bold-pop/karaoke/minimal, vertical safe zone, escaping; SRT/VTT), bundled Inter 4.0 OFL (Regular/Bold/Black, `assets/fonts`), `reframe.py` (center, blur-pad; auto blur-pad when shapes differ >1.3x), `render.py` (cwd + relative filter names, absolute output path, optional HW encoder with libx264 fallback, loudnorm, VFR→CFR, audio-only background), `export.py` (clip_NN_slug.mp4/.srt/.vtt, metadata.json, captions.txt; work files removed), `pipeline.py` (analyze/render with JobEvents incl. overall %, cancel/error states), `snipscout run`. Real e2e: 158 s Spanish espeak video → 3 vertical clips in 1m38s incl. base model download, also offline. 91 tests + 2 slow green.

- **D0** design system in `design/` (author brief: warm paper/graphite, vermilion, IBM Plex): tokens.css (2 themes, AA verified by scripts/check_contrast.py), components.css, theme.js (no-flash), 8 screens + index (resultados [+vacío/cargando], inicio, procesando, editor, primer-arranque, error, ajustes), NOTES.md, screenshots in design/screenshots. **All screens APPROVED by the author (2026-11-05).**

## Decisions
- Project renamed **SnipScout** (package `snipscout`, CLI `snipscout`, env `SNIPSCOUT_*`, theme key `snipscout.theme`). Repo: https://github.com/datamauriciovaldez/SnipScout (branch `main`).
- Author approved: Whisper `base` default (Rápido=tiny, Preciso=small); embeddings optional download, TF-IDF default.
- ffmpeg probe cache: `<cache>/ffmpeg_probe.json`, keyed by path+size+mtime; only successes cached.
- benchmark_es.wav = first 10.5 s of the espeak-ng spike sample (note in THIRD_PARTY_LICENSES).
- Cohesion = mean pairwise cosine (centroid similarity was biased ~1/sqrt(n)); separate scales for TF-IDF (0.04) and embeddings (0.35).
- Farewells ("that's it", "eso es todo") are NOT closers.
- "Ver fotograma real" deferred to E2 (v0.2) as in the spec.
- CLI uses argparse (no extra dependency).
- CI not yet run on GitHub (no remote). Windows/macOS behaviour unverified until first push.

## Next
- **U1**: server (token, free port, SSE, /api/v1 contract), pywebview window + browser fallback, frontend skeleton (Preact+htm vendored, router, store, i18n ES/EN) reusing design/css/tokens.css + components.css.
