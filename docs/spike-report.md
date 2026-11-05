# H0 — Spike report

Date: 2026-11-05 · Machine: Linux container, Intel Xeon @ 2.80 GHz, 4 vCPU, 16 GB RAM, **no GPU**,
Python 3.13 (system) / 3.12 (spike venv), uv 0.11.32, system ffmpeg 6.1.1 (Ubuntu).
All numbers below were measured on this machine unless marked **unverified**. Scripts live in `spikes/`.

**Network note:** `huggingface.co` was blocked at first by the build sandbox. The author allowed it, and spikes 2 and 3
then ran. No HF token was present (no `HF_TOKEN` env var, no `~/.cache/huggingface/token`).

| # | Topic | Result | Decision |
|---|---|---|---|
| 1 | ffmpeg + libass + libx264 | ✅ system ffmpeg and imageio-ffmpeg both render | **GO** — imageio-ffmpeg as the bundled fallback |
| 2 | Whisper on CPU | ✅ tiny/base/small download token-free, RTF 0.14 / 0.18 / 0.38 | **GO** — default `base` |
| 3 | Multilingual embeddings | ✅ token-free, 241 MB, 8.4 s / 1000 sentences, weak-but-real signal | **GO (optional)** — see decision 6 |
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
Sample: 58.7 s of Spanish speech generated with `espeak-ng` 1.51 (13 sentences, 0.7 s gaps, sentence boundaries
saved as ground truth). faster-whisper 1.2.1, ctranslate2 4.8.5, `cpu`, `int8`, `language="es"`,
`word_timestamps=True`, `vad_filter=True`. Boundary error = |true sentence start/end − nearest word start/end|.

| Model | On disk | Load | Transcribe 58.7 s | RTF | Peak RSS | Boundary err median / p90 |
|---|---|---|---|---|---|---|
| tiny | 75 MB | 1.7 s | 8.3 s | 0.14 | 391 MB | 0.18 s / 0.31 s |
| base | 142 MB | 7.8 s* | 10.7 s | 0.18 | 594 MB | 0.10 s / 0.16 s |
| small | 464 MB | 16.3 s* | 22.2 s | 0.38 | 1132 MB | 0.08 s / 0.19 s |

\* Load time includes the first download. `small` ran concurrently with spike 3, so its numbers are pessimistic.
- Quality on this robotic espeak voice: `tiny` garbles a lot ("sonoligador yos"), `base` is mostly
  right, and `small` is nearly perfect (it even writes "80 %"). A real human voice is still **unverified** and will likely do better.
- HF repos `Systran/faster-whisper-{tiny,base,small}`: not gated, `license:mit`.
- **Bug found:** faster-whisper 1.2.1 accepts any `av>=11`, but PyAV 19.0.2 removed the `metadata_errors` kwarg, so
  `transcribe(path)` crashes. Root cause: PyAV API change. Fix used here: pass a float32 numpy array
  (we already extract 16 kHz mono WAV with ffmpeg), which bypasses PyAV decoding entirely.

## 3. Embeddings (`spikes/s3_embeddings.py`)
- fastembed 0.9.1, `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` →
  `Qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q` (not gated, `license:apache-2.0`).
- Download: 241 MB on disk (235 MB ONNX + 17 MB tokenizer), 9.4 s including load.
- 1000 sentences: 8.4 s (under contention with Whisper `small`); peak RSS 732 MB.
- Sanity: mean cosine between on-topic sentences (public speaking, mixed es/en) 0.18 vs off-topic 0.08.
  It separates topics, but by a modest margin. Still far better than TF-IDF (0.03–0.08 between related sentences in spike 6).

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
6. **Embeddings optional, not required:** TF-IDF cohesion stays the built-in baseline. The multilingual MiniLM
   (241 MB) is an optional download that improves topic cohesion. Pending the author's decision.
7. **Whisper model names:** Rápido = `tiny`, Equilibrado = `base` (default), Preciso = `small`.
8. **Never let faster-whisper decode files:** always pass the numpy array from our WAV. Avoids the PyAV breakage.
