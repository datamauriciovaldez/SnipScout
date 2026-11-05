# H0 — Spike report

Date: 2026-11-05 · Machine: Linux container, Intel Xeon @ 2.80 GHz, 4 vCPU, 16 GB RAM, **no GPU**,
Python 3.13 (system) / 3.12 (spike venv), uv 0.11.32, system ffmpeg 6.1.1 (Ubuntu).
All numbers below were measured on this machine unless marked **unverified**. Scripts live in `spikes/`.

**Network note:** this build environment's egress policy blocks `huggingface.co`.
Spikes 2 and 3 could not download models and are **BLOCKED, not failed**. PyPI, GitHub releases and
archive.ubuntu.com are reachable.

| # | Topic | Result | Decision |
|---|---|---|---|
| 1 | ffmpeg + libass + libx264 | ✅ system ffmpeg and imageio-ffmpeg both render | **GO** — imageio-ffmpeg as the bundled fallback |
| 2 | Whisper on CPU | ⛔ blocked (HF 403); sample + benchmark script ready | Pending |
| 3 | Multilingual embeddings | ⛔ blocked (fastembed sources are HF-only) | Pending; TF-IDF plan B is ready anyway |
| 4 | pywebview | ⚠️ partial: window + Range seek OK, H.264 fails in Qt | **GO** with fallback + preview proxy |
| 5 | uv installer | ✅ official installer → clean env with managed Python in 8 s | **GO** |
| 6 | Clip selection PoC | ⚠️ 3/3 planted moments in top-3, but transcript is synthetic | Weak evidence; recheck on real transcripts |

## 1. ffmpeg (`spikes/s1_ffmpeg.py`)
Rendered a 2 s 1080×1920 `testsrc2` + tone with an `.ass` file using per-word colour highlighting,
Spanish accents (`ñandú`) and a font loaded from a private `fontsdir` (Inter Bold, OFL). The ffmpeg
process ran with `cwd` set to the work folder, using relative names in the filter: `ass=subs.ass:fontsdir=fonts`.

| Source | Version | `ass` filter | libx264 | Render | Frame with subs ≠ without |
|---|---|---|---|---|---|
| System (apt) | 6.1.1 | yes | yes | OK, 1.73 s | yes |
| imageio-ffmpeg 0.8.1 (pip) | n9.0.2 | yes | yes | OK, 1.92 s | yes |
| static-ffmpeg 3.0 | — | — | — | **fetch failed** (403 from github raw in this sandbox) | — |

Visual check: the subtitle line is centred in the lower third, the active word is highlighted and the accents render correctly.
**Other platforms (checked by reading the build config, not executed):** the imageio-ffmpeg 0.8.1
wheels for `win_amd64` (101 MB binary), `macosx_12_0_arm64` (50 MB) and `macosx_10_13_x86_64` (78 MB)
all contain `--enable-libass --enable-libx264` (Windows also has `--enable-fontconfig --enable-libfreetype`).
Running them on real Windows/macOS: **unverified**.
**Gap:** imageio-ffmpeg ships **no `ffprobe`**.

## 2. Whisper (`spikes/s2_make_sample.py`, `spikes/s2_whisper.py`)
- faster-whisper 1.2.1 + ctranslate2 4.8.5 install from PyPI with no issues.
- Sample: 58.7 s of Spanish speech generated with `espeak-ng` 1.51 (13 sentences, 0.7 s gaps;
  sentence boundaries saved as ground truth in `out/sample_truth.json`).
- `WhisperModel("tiny")` → `httpx.ProxyError: 403` (huggingface.co blocked here). The script that measures
  real-time factor (RTF), RAM and word-timing error is ready: `python spikes/s2_whisper.py tiny base`.
- Public, token-free access to `Systran/faster-whisper-*`: **unverified** (needs HF access).

## 3. Embeddings
- fastembed 0.9.1 catalog: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` →
  source `Qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q`, declared size 0.22 GB, apache-2.0
  (catalog metadata, **unverified** download size and timing). The download failed with the same 403.
- `minishlab/potion-multilingual-128M` (MIT, 0.51 GB declared) is a static-embedding alternative.

## 4. pywebview 6.2.1 (`spikes/s4_webview.py`)
FastAPI server on `127.0.0.1` with a free random port and a hand-written `Range` → `206` endpoint.
Each test page opens a `<video>` and seeks to 15 s.

| Mode | H.264 mp4 | VP9 webm | Range requests seen |
|---|---|---|---|
| Browser fallback (Chromium via Playwright) | seek OK (t=15) | seek OK | `bytes=0-`, then mid-file ranges for webm |
| pywebview + Qt (PyQt6-WebEngine from pip, Xvfb) | **MEDIA_ERR 4 (not supported)** | seek OK | same |

- With no system libraries (`libEGL`, no `gi`), pywebview raises `WebViewException` → the
  **automatic browser fallback is required**, confirmed.
- Drag-and-drop full path: the source code of edgechromium, cocoa, gtk and qt has the `pywebviewFullPath` handling
  (`webview/util.py`). It was **not exercised at runtime** (there is no real drag in headless mode). Native file dialog:
  **not testable headless**.
- Windows uses EdgeChromium/WebView2, where H.264 is expected to work: **unverified**, part of the author's Windows test.

## 5. uv installer
- Official installers `uv-installer.sh` / `uv-installer.ps1` from GitHub releases (0.13.7);
  `UV_UNMANAGED_INSTALL=<dir>` installs into a private dir, `UV_NO_MODIFY_PATH` / `-NoModifyPath` exist.
- Clean test: fresh uv → `uv run --managed-python --python 3.12` on a fresh hatchling project
  (downloads Python 3.12.16 + numpy) → ran the entry point; **8 s total**. One internal 403 during
  install (a mirror; the installer fell back successfully).
- Windows `.ps1` run: **unverified**.

## 6. Ranking PoC (`spikes/s6_ranking.py`)
Synthetic 28-sentence Spanish talk with 3 planted "good" moments. Signals: hook lexicon (+ dangling-start
penalty), closure lexicon, TF-IDF cohesion; 15–30 s windows on sentence boundaries; greedy non-overlap.
- The 3 planted moments ranked #1–#3; the next ones were filler (scores ≈ 0).
- **Caveat:** the lexicon and the text were written by the same person → circular evidence.
- TF-IDF cohesion on short sentences is tiny (0.03–0.08) and barely separates candidates;
  embeddings (spike 3) or sentence-window smoothing will matter.
- Closure cut moment #3 one sentence early → the "complete thought" signal needs more weight (as the spec anticipated).

## Decisions that change the spec (proposed)
1. **ffmpeg resolution order:** system ffmpeg (if `ass` + `libx264` pass the real render test) →
   `imageio-ffmpeg` as a normal pip dependency. Drop `static-ffmpeg`. ffmpeg stays out of the repo. The GPL
   binary is installed by pip on the user's machine; note it in `THIRD_PARTY_LICENSES.md`.
2. **Probing without ffprobe:** use `ffprobe` when present; otherwise **PyAV** (`av`) for structured
   probing (streams, rotation, fps). The PyAV wheel's licence and size must be checked in H1.
3. **Preview proxy:** the frontend checks `video.canPlayType`/the `error` event. If the original or H.264 does not
   play (Qt backend), the server generates a lightweight VP9/WebM proxy.
4. **Linux:** prefer the browser fallback when GTK/Qt is missing (confirmed failure mode).
5. **Launchers** use the versioned GitHub-release uv installer with `UV_UNMANAGED_INSTALL` into the
   app's own folder (no PATH changes).
