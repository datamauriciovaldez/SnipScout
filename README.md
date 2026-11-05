# SnipScout

Turn a long video into short clips with word-by-word subtitles — **100% local**: no accounts, no API keys, works offline after a one-time model download.

> Work in progress (pre-v0.1). See `PROGRESS.md` for the current status and `docs/spike-report.md` for the technical validation.

## Dev quickstart

```bash
uv sync
uv run snipscout doctor
uv run pytest
```

## License

MIT. ffmpeg is not redistributed in this repository; it is used from your system or from the `imageio-ffmpeg` package.
