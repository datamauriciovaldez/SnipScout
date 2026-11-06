# PROGRESS

## Done
- **H0** spike: all 6 GO (6 = weak evidence). Details: docs/spike-report.md.
- **H1** skeleton: pyproject (hatchling, uv, ruff/mypy strict/pytest), `core/binaries.py` (env → system → imageio-ffmpeg, real libass+libx264 render probe, cached), typed errors, `config.py` (platformdirs, `SNIPSCOUT_OFFLINE` flag), `snipscout doctor [--json] [--no-cache]`, autonomy guard (test + CI), CI matrix ubuntu/windows/macos. 15 tests green.

- **H2** core data: `models.py` (MediaInfo, Transcript, Project, JobEvent…), `storage.py` (atomic JSON, id validation vs path traversal), `ingest.py` (ffprobe or PyAV; rotation, VFR, multi-track, cover-art skip), `audio.py` (16 kHz mono WAV, track select, limit, RMS), `procs.py` (ffmpeg progress + CancelToken), `net.py` (SNIPSCOUT_OFFLINE socket guard, loopback allowed). 42 tests green; media fixtures use paths with spaces/accents/emoji.
- **H3** `modelstore.py` (pinned HF revisions + sha256, own HTTP client: byte progress, pause/resume via Range, cancel, offline refusal), `transcribe.py` (5-min chunks with boundary-segment redo, resumable from `processed_until`, quick analysis 10 min, live text + ETA events, RTF stats in `<cache>/speed.json`, bundled 10 s benchmark `assets/benchmark_es.wav`, GPU optional w/ CPU fallback), `segment.py` (punctuation/0.6 s pause/40 words, wps, pauses, confidence, RMS dynamics, fillers), lexicons `core/text/data/{es,en}.json`. 60 tests + 1 slow (real tiny) green.
- **H4** selection: `candidates.py` (sentence-boundary windows, cheap shortlist), `scoring/heuristic.py` (7 signals hook/pace/energy/cohesion/closure/autonomy/confidence → 0-100 + reason keys), `scoring/weights.toml` (single documented tuning file), `refine.py` (padding without touching neighbours, MMR diversity, no overlaps), `text/extract.py` (extractive hook/title), TF-IDF keywords, `select.py` entry point, lexicons es/en, optional `[embeddings]` extra (fastembed). `scripts/eval_scoring.py` + 2 synthetic annotated talks: recall@5 = 7/7 with TF-IDF and with embeddings (synthetic → weak evidence). 72 tests green.
- **H5** output: `subtitles.py` (ASS one event per word, 3-5 word lines, no orphans, presets classic/bold-pop/karaoke/minimal, vertical safe zone, escaping; SRT/VTT), bundled Inter 4.0 OFL (Regular/Bold/Black, `assets/fonts`), `reframe.py` (center, blur-pad; auto blur-pad when shapes differ >1.3x), `render.py` (cwd + relative filter names, absolute output path, optional HW encoder with libx264 fallback, loudnorm, VFR→CFR, audio-only background), `export.py` (clip_NN_slug.mp4/.srt/.vtt, metadata.json, captions.txt; work files removed), `pipeline.py` (analyze/render with JobEvents incl. overall %, cancel/error states), `snipscout run`. Real e2e: 158 s Spanish espeak video → 3 vertical clips in 1m38s incl. base model download, also offline. 91 tests + 2 slow green.

- **D0** design system in `design/` (author brief: warm paper/graphite, vermilion, IBM Plex): tokens.css (2 themes, AA verified by scripts/check_contrast.py), components.css, theme.js (no-flash), 8 screens + index (resultados [+vacío/cargando], inicio, procesando, editor, primer-arranque, error, ajustes), NOTES.md, screenshots in design/screenshots. **All screens APPROVED by the author (2026-11-05).**
- **U1** server + shell: `web/app.py` (FastAPI, full /api/v1 contract incl. SSE events, model download SSE, Range media, waveform peaks, thumbnails, export.zip, reveal; preview-frame = 501 until v0.2), security (session token → HttpOnly SameSite=Strict cookie, Host/Origin checks, no CORS, upload streaming with sanitised names and size limit), `web/jobs.py` (threaded jobs, event fan-out/replay, cancel, busy=409), `desktop.py` (`snipscout ui`: free port, pywebview window with file/folder dialogs, automatic browser fallback — verified 0.1 s fallback without GTK/Qt), frontend skeleton (Preact 10.24.3 + hooks + htm 3.1.1 vendored via import map, hash router, store, i18n ES/EN with completeness tests, error screens per error code, theme/lang persistence). Design system moved to `web/static` (design/ screens link to it). 109 tests green; browser run: no console errors, theme+lang persist.
- **U2** components: `js/components.js` (Button incl. loading/disabled/icon/kbd, Checkbox, Segmented, Tag, ScoreBar, Progress incl. indeterminate, Thumb, Wave, Field, Modal with focus trap/Esc/focus return, Toaster/toast(), Stepper, ErrorNotice), `js/icons.js` (one 24px round-stroke set + Logo), SVG favicon. Gallery `design/screens/componentes.html` + `scripts/check_components.py` (Playwright: no console errors, icons, i18n, modal focus, toast, ARIA) passing in light and dark. Contrast: scripts/check_contrast.py (AA, both themes).
- **U3** first run + Home: `views/welcome.js` (01 language, 02 computer check + model choice with per-hour estimates, 03 real download via SSE with pause/resume/verify and "only once"; Home redirects there when no model is installed), `views/home.js` (drop zone: real paths via pywebview DOM drop handler in window mode / streamed upload in browser mode, Ctrl+O, native or <input> picker; queue with probe metadata, upload progress, remove; settings table (length, format, subtitle style with preview, language, advanced accuracy limited to installed models, quick analysis); remembered defaults; honest estimate (initial vs measured); recent projects). Real browser e2e with a fresh data dir: first run → tiny download (paused at 10 %, resumed, verified) → upload 158 s video → analyze → 7 clips, no console errors. Native window drop/dialogs: unverified (no GUI here).
- **U4** Processing + Results + simple editor: `views/project.js` (route switches Processing ↔ Results by status/job; Processing = SSE stages, real waveform darkening by heard time, live transcript, honest ETA, cancel via modal, resume from saved point, error screen; Results = approved reference layout with real thumbnails, include/exclude (PATCH), keyboard ↑↓/Space/Enter, preview panel with clip player + approximate word subtitle, "why it works" points per signal, mini waveform with in/out markers, transcript lines, copy title, Download (single clip) and Render N clips → export route; empty state), `views/editor.js` (in/out with sentence snap and typed timecodes, title, per-word corrections/hide, style, Ctrl+Enter save, reset), `views/player.js`. API: GET /transcript, clip contributions, render clip_ids, default output folder `Downloads/SnipScout/<project>` (SNIPSCOUT_OUTPUT_DIR). Fixed: job looked busy after its terminal event (race) → regression test. Top 3 clips pre-selected. Browser e2e (results, editor save, processing cancel→resume→results): no console errors.
- **U5** export + final + review: `views/export.js` (per-clip render progress from SSE with clip id/title, cancel with confirm, finished list with hover-play previews, Download (accent), Copy title+description, .srt/.vtt, ZIP, Show in folder), API `GET /exports` + `GET /exports/{name}` (Range, attachment, whitelist of names), pywebview downloads enabled, typed `reveal_failed` error, real 404 screen. Visual review in dark at 1440×900 and 1000×680 (home, results, editor, final): fixed Results at 1000 px (hide in/out column, narrower side, trimmed status bar); fixed a null-ref console error in the player. 114 tests green; AA contrast passes.
- **S1** done (author verified the Windows double-click launch): launchers (Start-SnipScout.bat CRLF, start-snipscout.sh / Start-SnipScout.command; uv installed into ./.uv only with consent, managed Python 3.12, `uv sync --no-dev`, error log), new-user test in a clean folder with no uv: 48 s to `doctor` OK, 57 s for a real `run` incl. model download (Linux; Windows/macOS by the author), README v0.1 with real screenshots (demo talk, synthetic voice), THIRD_PARTY_LICENSES completed, CI (+contrast, launcher checks, concurrency, timeout), release.yml (tag = version check, sdist+wheel, windows .zip and macos-linux .tar.gz via git archive with export-ignore, notes from CHANGELOG), CHANGELOG 0.1.0, version 0.1.0. Fixed: Windows CI had failed mypy since U1 (unused ignore on os.startfile) so Windows tests weren't running.
- **v0.1.0 RELEASED** 2026-11-05: https://github.com/datamauriciovaldez/SnipScout/releases/tag/v0.1.0 (published by the author via Actions → Release → Run workflow; assets verified: .bat CRLF, launchers executable in .tar.gz, no dev/local files). CI green on Linux/Windows/macOS (macOS runner occasionally not assigned → shows "cancelled" with 0 steps).
- **E1** canvas timeline (`views/timeline.js`): waveform peaks fetched per visible range at one value per CSS pixel (`GET /waveform?start&end`, envelope cached as .npy keyed by WAV mtime, heights normalised on the whole file), DPR-sharp drawing with token colours (repaints on theme change), region + accent handles + playhead + ruler, drag handles snapping to the nearest sentence boundary (Alt = free, min 1 s), click/drag to scrub (player seeks), Ctrl+wheel zoom around cursor, wheel pan, −/+/fit buttons. Player: external seek + time reporting, loops only while playing. Browser e2e: snap verified (45.45 = sentence end), Alt free, seek exact, zoom refetches range, save OK, no console errors.
- **E2** transcript sync + real frame: editor words follow playback (binary search on word starts, cleared in pauses, auto-scroll), click a word to seek, double-click to edit; `POST /clips/{cid}/preview-frame` renders one JPEG with the export's reframe + libass for the *unsaved* draft (ASS shifted so 0 s = requested time) via `render.render_still` + `subtitles.shift_words`; modal with the real frame. Browser e2e: click-to-seek exact (22.76→22.77), highlight advances 56→59 while playing, real frame 1080×1920, no console errors.
- **E3** shortcuts + undo + autosave: pure helpers `js/editing.js` (bounded undo/redo history, nearest boundary, word stepping) with `node --test` unit tests run from pytest (`tests/js/`, skipped without node); editor: every confirmed change is one undo step (a handle drag = 1 step, title on blur), Ctrl/Cmd+Z / Shift+Z / Y, I/O set in/out at the playhead snapped to sentences (Alt exact), ←/→ previous/next word (Shift ±5 s), Ctrl/Cmd+Enter save and back; autosave 0.9 s after the last change with indicator (pending/saving/saved/error); Reset returns to the clip as opened. Browser e2e: O→137.41 autosaved, undo→152.83, redo→137.41, → to next word exact, no console errors. Not browser-verified: drag-as-single-undo-step (logic in place).
- **E4** projects + settings + resume: `views/projects.js` (search, rename button, delete with confirm, reveal, clip counts), `views/resume.js` (last project/clip/export location in localStorage → "Continue where you left off" on Home), `views/settings.js` (language, theme, output folder via native picker or path input + reset, export quality light/standard/high = CRF 24/20/17, hardware encoder and loudnorm toggles, speech models download/default/delete, disk usage + Free up space). Core `preferences.py` (`<data>/preferences.json`); `config.output_dir()` = env → preference → Downloads/SnipScout; render options read preferences. API: GET/PATCH /settings, GET /system/storage, POST /system/storage/free (caches + orphan uploads only), DELETE /system/models/{name}, clip counts in project list. Fixed: double-click rename on a link navigated away (rename is a button now). Browser e2e OK; README screenshots regenerated. Version 0.2.0 + CHANGELOG.

- **v0.2.0 RELEASED** 2026-11-06 (author ran the Release workflow; assets verified: .bat CRLF, launchers executable, no dev/local files).
- **P1** polish: `scripts/check_a11y.py` (every screen × light/dark × 100/200 % zoom: axe-core WCAG 2.1 AA, ≥ 40 px targets
  incl. `::before` hit areas, Tab walk with visible focus/no trap, no horizontal scroll at 720 px) → **0 problems**
  (started at ~120: 34 px controls, nested interactive results rows, `aria-selected` on plain rows, .kbd contrast,
  6 px overflow in the editor top bar). Results list is now an ARIA grid; `LiveStatus` announces progress once per
  stage/10 % (Processing, Export, model download); motion = view fade-in, score bars grow, selected-row marker (transform/
  opacity only, 0 ms + static indicators with reduced motion); narrow/200 % layout (Results stacks, timeline labels
  never overlap, compact top bar); Projects renders 50 rows at a time + `content-visibility` (400 projects: ~550 → 130–250 ms
  to open, filter 52 → 30 ms; headless Chromium). Light theme reviewed on every screen. Other lists are already bounded
  (live transcript ≤ 41 lines, editor context window, ≤ 15 results).

- **P2** optional local AI: `core/scoring/ollama.py` (`OllamaClient` status/rate over httpx with `trust_env=False`, loopback
  only incl. `SNIPSCOUT_OLLAMA_URL`; `rerank` rates top-15 one request per clip with Ollama structured output
  `format` = `Rating` JSON schema, temperature 0, excerpt sent as a JSON string in the user message and the system prompt
  forbids following it; malformed/timeout → that clip keeps its heuristic result, none rated → `ollama_failed`;
  missing server/model → `ollama_unavailable`), `Clip.ai_score`/`ai_title`, `Pipeline.improve` (never changes the
  project status), API `GET /system/ollama`, `POST /projects/{id}/improve` (job kind "improve", SSE), preference
  `ollama_model`. UI: Results "Mejorar con IA local" (disabled with explanation when Ollama is absent, progress,
  cancel, toast, lead text changes), "IA local n/10" in "why", suggested title with *Use*; Settings "IA local (opcional)"
  (status, re-check, model select). Tests with httpx.MockTransport (6) incl. prompt-injection excerpt; browser e2e
  against a fake Ollama server (on/off), a11y audit still 0 problems. 124 tests green.
  Quality tuning from author annotations: **pending** — needs 3–4 real videos annotated by the author
  (`eval/annotations/*.json`); optional per spec.

- **P3** CI/docs/community: CI jobs `ui` (smoke_ui.py: real server + 401 without session + first-run screens light/dark
  in Chromium, no console errors, no raw i18n keys, screenshots artifact; check_components.py) and `audit`
  (pip-audit, continue-on-error; locally "No known vulnerabilities"), `check_licenses.py` in the test matrix (all 16
  runtime packages match their metadata; fastembed row added), `slow.yml` (dispatch + weekly), Dependabot (uv +
  actions, grouped). Docs architecture/api/scoring/troubleshooting (claims checked against the code), SECURITY,
  CODE_OF_CONDUCT (Contributor Covenant 2.1 text), CONTRIBUTING, issue forms + PR template; README links them.
  Author action suggested: enable *Private vulnerability reporting* in repo Settings → Security.

- **P4** media/measurements/packaging: `scripts/make_screenshots.py --gif` (frame capture + ffmpeg palette GIF, 2.3 MB;
  Playwright video needs its own ffmpeg, avoided) → README header GIF + 4 screenshots per theme regenerated from the
  re-analysed demo; `scripts/benchmark.py` (fresh process per model, psutil peak RSS) → tiny/base/small 4.1/5.4/11.7 s
  per audio minute, 0.43/0.53/0.79 GB (v0.1 numbers were ~2× slower; cause not isolated; README says so);
  `packaging/snipscout_frozen.py` + `.github/workflows/pyinstaller.yml` (manual, 3 OS, doctor smoke test, artifact
  with BUNDLE-README) — local Linux build 593 MB, `doctor` OK and full offline `run` with the bundled imageio ffmpeg
  (no PATH) in 40 s. Version 0.3.0, CHANGELOG 0.3.0, 124 tests green.

- **Fix before v0.3.0**: Windows CI caught a 500 in `test_busy_and_cancel` — a transient sharing violation
  (PermissionError) when reading/replacing `project.json` while the job thread writes it. `storage.retry_sharing`
  retries reads and replaces (8 tries, ~0.7 s); regression test added. CI green on all OS (b51e59b).

- **v0.3.0 RELEASED** 2026-11-06 (author ran the Release workflow; assets verified: .bat CRLF, launchers executable,
  sdist version 0.3.0, docs/GIF/SECURITY included, no dev/local files). **All spec milestones (H0–P4) are done.**

## Decisions
- Playwright in CI is pinned (`uv run --with playwright==1.64.1`) instead of a dev dependency, so normal installs stay small.
- Ollama re-ranking: combined = 0.5 × heuristic + 0.5 × (rating × 10); only top 15 are rated; per-clip requests so
  progress/cancel work on a CPU; suggested titles never overwrite the user's title automatically.
- Spec "targets ≥ 40 px": compact 34 px controls keep the approved look and get an invisible `::before` hit area
  (`--target-min`); text-only links get padding + negative margin. Inline words in the transcript are exempt (WCAG inline).
- axe-core (MPL-2.0) is only a dev-time input to the audit script, never vendored or shipped.
- This session cannot push git tags (HTTP 403): releases are published from Actions → Release → Run workflow (creates tag v<pyproject version>).
- Project renamed **SnipScout** (package `snipscout`, CLI `snipscout`, env `SNIPSCOUT_*`, theme key `snipscout.theme`). Repo: https://github.com/datamauriciovaldez/SnipScout (branch `main`).
- Author approved: Whisper `base` default (Rápido=tiny, Preciso=small); embeddings optional download, TF-IDF default.
- ffmpeg probe cache: `<cache>/ffmpeg_probe.json`, keyed by path+size+mtime; only successes cached.
- benchmark_es.wav = first 10.5 s of the espeak-ng spike sample (note in THIRD_PARTY_LICENSES).
- Cohesion = mean pairwise cosine (centroid similarity was biased ~1/sqrt(n)); separate scales for TF-IDF (0.04) and embeddings (0.35).
- Farewells ("that's it", "eso es todo") are NOT closers.
- "Ver fotograma real" deferred to E2 (v0.2) as in the spec.
- CLI uses argparse (no extra dependency).
- CI runs on GitHub for every push to main (ubuntu/windows/macos + autonomy guard). Last verified green: 91610d4 (macOS runner not assigned that time).
- Accent colour only for: high scores, active subtitle word, wave markers/handles, active row, Download button.
- Output folder resolution: `SNIPSCOUT_OUTPUT_DIR` → preferences.json → Downloads/SnipScout/<project>.

## Current state
- Version **0.3.0** released (v0.1.0, v0.2.0, v0.3.0 published). Dependabot opens weekly PRs (author merges).
- Tests: 124 passed + 2 slow deselected (`uv run pytest -q -m "not slow"`).

## Next
- Spec complete. Optional: author runs Actions → Experimental bundle to try the PyInstaller build on Windows/macOS.
- Possible next work (scope change → needs the author's decision): real-video scorer tuning with annotated talks
  (`eval/annotations/*.json`), H.264→VP9 preview proxy for the Qt webview (spec 5.6, only Linux/Qt), face-aware
  reframing, signed installers.
