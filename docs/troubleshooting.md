# Troubleshooting

Start with **`snipscout doctor`** (or `Start-SnipScout.bat doctor` on Windows): it checks Python, ffmpeg (with a
real render using subtitles), ffprobe/PyAV, CPU, RAM, the data folder, free disk space and the offline flag.
If the launcher fails it writes **`snipscout-error.log`** next to it — attach that file to an issue.

## Starting the app

| Symptom | What to do |
|---|---|
| Windows: "Windows protected your PC" (SmartScreen) | The launcher is a downloaded script. *More info → Run anyway*. |
| Windows: blank or no window | The window uses Microsoft WebView2 (built into Windows 10/11). Install the "Evergreen" WebView2 runtime from Microsoft if it was removed. |
| macOS/Linux: "permission denied" on the launcher | ZIP files drop the executable bit. Use the `.tar.gz` release or `chmod +x start-snipscout.sh`. macOS: right-click `Start-SnipScout.command` → *Open*. |
| Linux: opens in the browser instead of a window | No GTK or Qt webview libraries were found. Either is fine; e.g. on Debian/Ubuntu `sudo apt install gir1.2-webkit2-4.1` (GTK) — or keep using the browser. |
| "Open SnipScout from its window" | The page was opened without the session link. Close it and start SnipScout again. |
| The preview says it is preparing a light copy | The window can't play this video's format (e.g. HEVC from an iPhone). SnipScout makes a small WebM copy once, just for the preview; exports use the original. |
| "The app isn't responding" | The local server stopped. Close SnipScout and open it again. |

## Error screens

Every error screen has a stable code (also returned by the API) and a *Copy technical details* button.

| Code | Meaning | Fix |
|---|---|---|
| `ffmpeg_missing` | No ffmpeg with libass + libx264 was found. | Reinstall (the `imageio-ffmpeg` dependency provides one) or install a full ffmpeg, or point `SNIPSCOUT_FFMPEG` to it. |
| `ffmpeg_failed` | ffmpeg failed on a clip. | Try another export format or quality; report with the technical details. |
| `unsupported_media` | Not a readable video/audio file. | Try MP4, MOV, MKV, WEBM, MP3, WAV or M4A; re-save damaged files. |
| `no_speech` | Only music or silence. | If the file has several audio tracks, the app uses the first; pick another with `snipscout run video.mp4 --track 1`. |
| `model_download` | The speech model could not be downloaded. | Check the connection (huggingface.co must be reachable); retry — it resumes. |
| `offline` | `SNIPSCOUT_OFFLINE=1` blocked a needed download. | Unset it once to download the model. |
| `storage` | Data could not be saved. | Free disk space (Settings → *Free up space* removes only caches) or choose another output folder. |
| `job_busy` | Something is already running for this project. | Wait or cancel it. |
| `reveal_failed` | No file manager could be opened. | Copy the folder path shown and open it yourself. |
| `ollama_unavailable` | Local AI: Ollama is not running or lacks the model. | Start Ollama and install a model with Ollama itself; SnipScout never downloads one. |
| `ollama_failed` | Local AI gave no usable answer. | Try a smaller/faster model; your clips are unchanged. |

## Speed and resources

- Analysis time depends mostly on the speech model. On a 4-vCPU machine without GPU, Balanced (`base`) transcribed
  about 5.4 s per minute of audio; Fast (`tiny`) about 4.1 s; Accurate (`small`) about 11.7 s
  (`scripts/benchmark.py`). Laptop timings are not measured yet; SnipScout measures your machine after the first
  analysis and updates its estimates. Measure yours with `uv run python scripts/benchmark.py your-video.mp4`.
- Long videos are processed in 5-minute chunks; you can cancel and resume later without losing progress.
- *Quick analysis* only listens to the first 10 minutes.
- Exports use libx264 by default. *Hardware encoder* (Settings) tries the GPU encoder and falls back automatically.

## Privacy checks

- Run with `SNIPSCOUT_OFFLINE=1` to be sure nothing leaves the computer after the model download.
- Data folders are listed in [architecture](architecture.md#where-data-lives); deleting a project removes its folder,
  not your original video or exported clips.
