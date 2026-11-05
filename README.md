# ClipForge

Turn a long video into short clips with word-by-word subtitles — **100% local**: no accounts, no API keys, works offline after a one-time model download.

> Work in progress (pre-v0.1). See `docs/SPEC.md` for the plan and `PROGRESS.md` for the current status.

## Dev quickstart

```bash
uv sync
uv run clipforge doctor
uv run pytest
```

## License

MIT. ffmpeg is not redistributed in this repository; it is used from your system or from the `imageio-ffmpeg` package.
