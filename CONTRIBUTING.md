# Contributing

Thanks for helping. SnipScout has a few non-negotiable principles; please keep them in every change:

- **100 % local.** No accounts, telemetry, API keys or paid services. The only network use is the one-time model
  download (and the user's own Ollama on `127.0.0.1`). CI fails if `src/` references keyed AI APIs.
- **A normal laptop CPU is the target.** A GPU may speed things up but is never required.
- **It proposes, you decide.** Clip selection is explainable; titles are extractive unless the user asks local AI.
- **Honest numbers.** Anything not measured is labelled "not measured yet".

## Setup

```bash
uv sync
uv run pytest
uv run snipscout ui
```

`ffmpeg` with libass and libx264 is needed for rendering tests; `imageio-ffmpeg` (a dependency) provides one.

## Before opening a pull request

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy src
uv run pytest -q
uv run python scripts/check_contrast.py
```

UI changes: run `scripts/check_components.py` and, with a running app, `scripts/check_a11y.py` (both need
Playwright). New visible text goes into **both** `static/i18n/es.json` and `en.json` (a test checks this).
Colours only come from `static/css/tokens.css`.

## Code layout

See [`docs/architecture.md`](docs/architecture.md). In short: `core/` is the engine and never imports `web`,
`cli` or `desktop`; long steps report `JobEvent`s and honour a `CancelToken`; errors are `SnipScoutError`
subclasses with stable codes; subprocesses use argument lists with timeouts (never `shell=True`).

## Commits

Conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`), one topic per pull request. By contributing
you agree that your work is released under the MIT licence and you follow the [Code of Conduct](CODE_OF_CONDUCT.md).
