# SnipScout

**Turn a long video into short clips with word-by-word subtitles — on your own computer.**
No accounts, no API keys, no uploads. After a one-time model download it works fully offline.

![Results screen: suggested moments ranked by score, with a preview of the selected clip](docs/screenshots/results-light.png)

| Start | Clip editor | Finished clips (dark theme) |
|---|---|---|
| ![Home](docs/screenshots/home-light.png) | ![Editor](docs/screenshots/editor-light.png) | ![Export](docs/screenshots/export-dark.png) |

## Why this exists

Cutting a talk, class or podcast into short clips usually means either hours of manual scrubbing or a paid
cloud service that uploads your footage. SnipScout does the boring part locally: it listens to the whole
video, proposes the moments that work on their own, and renders vertical clips with burned-in subtitles.
**It proposes; you decide.**

## Features

- Drag a video (or audio) file in; analysis runs on a normal laptop CPU — a GPU is used only if present.
- 10–15 suggested moments, each with a score and the reasons behind it ("opens with a question", "ends with a punchline"…).
- Simple editor: snap in/out points to sentence boundaries, fix any subtitle word, pick a subtitle style.
- Export to 9:16, 1:1, 16:9 or original, with word-by-word highlighted subtitles (4 styles), plus `.srt`/`.vtt`,
  `metadata.json` and a ready-to-paste title and description per clip.
- Spanish and English interface, light and dark themes, keyboard friendly.

## Quickstart

**Windows** — download the ZIP from the [latest release](https://github.com/datamauriciovaldez/SnipScout/releases),
unzip it and double-click **`Start-SnipScout.bat`**. The first run asks before installing
[uv](https://docs.astral.sh/uv/) into that folder, prepares Python (a few hundred MB, only once) and opens the app.
Windows may show a SmartScreen warning for a downloaded script: choose *More info → Run anyway*.
The window uses Microsoft WebView2, which is already installed on Windows 10/11.

**macOS / Linux** — one line (needs [uv](https://docs.astral.sh/uv/getting-started/installation/)):

```bash
uv tool install git+https://github.com/datamauriciovaldez/SnipScout && snipscout ui
```

Or use the release `.tar.gz` and run `./start-snipscout.sh` (Linux) / right-click `Start-SnipScout.command` →
*Open* (macOS). ZIP files lose the executable bit, so on macOS/Linux prefer the `.tar.gz` or `chmod +x` the launcher.
On Linux without GTK/Qt webview libraries, SnipScout opens in your default browser instead of its own window.

**Command line**: `snipscout run video.mp4 --count 3` analyzes and exports the top 3 clips; `snipscout doctor` checks your setup.

## How it works

```mermaid
flowchart LR
  A[Video / audio] --> B[16 kHz audio]
  B --> C[Speech to text<br/>faster-whisper, word timestamps]
  C --> D[Sentences + prosody<br/>pace, pauses, energy]
  D --> E[Candidate windows<br/>on sentence boundaries]
  E --> F[Explainable scoring<br/>+ diversity]
  F --> G[You review and edit]
  G --> H[ffmpeg render<br/>reframe + ASS subtitles]
```

Clip selection uses **no language model**. A heuristic scorer combines seven signals — opening hook, pace,
vocal energy, topic cohesion, clean ending, whether it makes sense without context, and transcription
confidence — with weights in a single documented file (`src/snipscout/core/scoring/weights.toml`).
Titles, hooks and keywords are **extracted** from what was said, never generated. The suggestions are a
starting point: the editor is there because you know your content better.

## 100% local & private

- Your files never leave your computer; there is no telemetry and no login.
- The only network access is the one-time speech-model download from Hugging Face (public, no token),
  and fetching `uv` / Python packages on first run. `SNIPSCOUT_OFFLINE=1` blocks any other connection.
- The local server listens on `127.0.0.1` only and requires a per-session token.

## Requirements & performance

Python 3.11+ (installed automatically by the launchers). Disk, measured on Linux: about 0.85 GB for Python,
the environment and the Fast model (+70 MB for Balanced), plus a ~0.6 GB download cache that uv keeps and you can
delete (`uv cache clean`); Windows sizes are not measured yet. 4 GB of RAM or more is recommended. Measured on a 4-vCPU cloud container (Intel Xeon 2.8 GHz, no GPU) with a synthetic Spanish voice:

| Speech model | Download | Time per minute of audio | Peak RAM |
|---|---|---|---|
| Fast (`tiny`) | 78 MB | ≈ 8.5 s | 0.4 GB |
| Balanced (`base`, default) | 148 MB | ≈ 11 s | 0.6 GB |
| Accurate (`small`) | 486 MB | ≈ 23 s | 1.1 GB |

A 2:38 talk went from file to three exported vertical clips in 1 min 38 s with the Balanced model
(including its download). Laptop timings are **not measured yet**; SnipScout measures your machine's real
speed and adjusts its estimates after the first analysis.

## Limitations & roadmap

- Selection quality has only been tuned on synthetic transcripts so far; expect to adjust suggestions.
- Reframing is center-crop or blurred background; no face tracking.
- The preview in the app approximates the subtitle rendering; the exported file is the reference.
- Native window on macOS and real Windows hardware are **not yet verified**.
- v0.2: waveform timeline with draggable handles, full transcript editing, undo, projects history.
- v0.3: polish, accessibility review, optional local-LLM re-ranking (Ollama, if you already run it), packaging.

## Responsible use

Only process content you own or have permission to use. Respect copyright and each platform's rules
when you publish clips. SnipScout works on local files only; downloading videos from websites is out of scope.

## Architecture & contributing

`src/snipscout/core` is the processing engine (no UI imports), `web/` is the local API and the Preact frontend
(no build step), `desktop.py` opens the window. See [`PROGRESS.md`](PROGRESS.md) and
[`docs/spike-report.md`](docs/spike-report.md).

```bash
uv sync
uv run pytest
uv run snipscout ui
```

## License & credits

MIT © datamauriciovaldez. Speech recognition by [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
(Whisper models, MIT). Fonts: IBM Plex and Inter (SIL OFL). Full list in
[`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md). ffmpeg is not redistributed in this repository.
