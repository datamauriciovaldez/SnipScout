"""Browser end-to-end test of the whole flow with a fake speech model (no downloads, no GPU):
upload → analyze → results → editor (edit + save) → render → finished clips.

Needs Playwright with Chromium; skipped otherwise. CI runs it in the `ui` job. Locally:
  SNIPSCOUT_E2E_CHROMIUM=/path/to/chromium uv run --with playwright pytest tests/e2e
"""

from __future__ import annotations

import os
import secrets
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from snipscout.core import modelstore
from snipscout.core.audio import SAMPLE_RATE
from snipscout.core.binaries import FfmpegBinaries
from snipscout.core.storage import ProjectStore
from snipscout.desktop import start_server
from snipscout.web.app import Context

sync_api = pytest.importorskip("playwright.sync_api")
sys.path.insert(0, str(Path(__file__).parents[1]))
from conftest import _make  # noqa: E402
from test_transcribe_segment import FS, FW, Info  # noqa: E402

SENTENCES = [
    "¿Sabéis cuál es el error número uno al hablar en público?",
    "Hablar demasiado rápido porque tenemos miedo al silencio.",
    "El silencio no es tu enemigo, es tu herramienta.",
    "Una pausa a tiempo hace que todos te miren.",
    "Por eso hoy vamos a practicar tres ejercicios sencillos.",
    "El primero es respirar antes de cada idea importante.",
    "El segundo es mirar a una persona distinta en cada frase.",
    "Y el tercero es terminar siempre con una frase corta y clara.",
]


class FakeSpeech:
    """Speaks SENTENCES in a loop, about 2.5 words per second, with real punctuation."""

    def transcribe(self, audio: np.ndarray, **kw: Any) -> tuple[list[FS], Info]:
        n = len(audio) / SAMPLE_RATE
        segs, t, k = [], 0.0, 0
        while True:
            words = SENTENCES[k % len(SENTENCES)].split()
            if t + len(words) * 0.4 > n:
                break
            fw = [FW(t + i * 0.4, t + i * 0.4 + 0.32, w) for i, w in enumerate(words)]
            segs.append(FS(fw[0].start, fw[-1].end, " ".join(words), fw))
            t = fw[-1].end + 0.7
            k += 1
        return segs, Info()


@pytest.fixture
def app_url(
    tmp_path: Path, ff: FfmpegBinaries, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[str, Path]]:
    monkeypatch.setenv("SNIPSCOUT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SNIPSCOUT_CACHE_DIR", str(tmp_path / "cache"))
    out = tmp_path / "out"
    monkeypatch.setenv("SNIPSCOUT_OUTPUT_DIR", str(out))
    # Pretend the default model is installed so the app skips the first-run download.
    d = modelstore.model_dir("base")
    d.mkdir(parents=True)
    for f in (*modelstore.FILES, ".verified"):
        (d / f).write_text("x")
    ctx = Context(
        ProjectStore(tmp_path / "data" / "projects"),
        ff,
        secrets.token_urlsafe(32),
        model_loader=lambda name: FakeSpeech(),  # type: ignore[arg-type,return-value]
        uploads_dir=tmp_path / "uploads",
    )
    server, port = start_server(ctx)
    try:
        yield f"http://127.0.0.1:{port}/?t={ctx.token}", out
    finally:
        server.should_exit = True


@pytest.fixture
def talk(ff: FfmpegBinaries, tmp_path: Path) -> Path:
    """75 s of video with a tone, under a path with spaces and accents."""
    return _make(
        ff,
        tmp_path / "mis vídeos" / "charla de práctica.mp4",
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=640x360:r=25:d=75",
            "-f",
            "lavfi",
            "-i",
            "sine=f=220:d=75",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
        ],
    )


def test_full_flow(app_url: tuple[str, Path], talk: Path) -> None:
    url, out = app_url
    exe = os.environ.get("SNIPSCOUT_E2E_CHROMIUM") or None
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=exe)
        page = browser.new_page(viewport={"width": 1440, "height": 900}, locale="en-US")
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.set_default_timeout(60_000)

        # Home: upload through the browser file picker, then start.
        page.goto(url)
        page.wait_for_selector(".home")
        page.set_input_files(".home input[type=file]", str(talk))
        go = page.locator("button", has_text="Find my best clips")
        sync_api.expect(go).to_be_enabled()
        go.click()

        # Processing → Results.
        page.wait_for_selector(".results [role=row]")
        rows = page.locator(".results [role=row]")
        assert rows.count() >= 2
        assert page.locator(".results [role=row] input[type=checkbox]:checked").count() >= 1
        first_title = page.locator("#row-c01 .row__title").inner_text()
        assert first_title

        # Keyboard: next row, toggle it, open the first clip in the editor.
        box = page.locator("#row-c02 input[type=checkbox]")
        was = box.is_checked()  # the best 3 come pre-ticked
        page.focus("#row-c01")
        page.keyboard.press("ArrowDown")
        page.keyboard.press("Space")
        sync_api.expect(box).to_be_checked(checked=not was)
        page.keyboard.press("Space")
        sync_api.expect(box).to_be_checked(checked=was)
        page.keyboard.press("ArrowUp")
        page.keyboard.press("Enter")
        page.wait_for_url("**/clip/c01")

        # Editor: rename the clip, autosave, back to results.
        page.wait_for_selector(".editor .word")
        title = page.locator(".editor__title")
        title.fill("My edited clip")
        title.press("Tab")
        sync_api.expect(page.locator(".save-state--pending")).to_be_visible()  # autosave is scheduled ...
        sync_api.expect(page.locator(".save-state--saved")).to_be_visible()  # ... and done
        page.keyboard.press("Control+Enter")
        page.wait_for_selector(".results [role=row]")
        sync_api.expect(page.locator("#row-c01 .row__title")).to_have_text("My edited clip")

        # Render the ticked clips and wait for the finished list.
        ticked = page.locator(".results [role=row] input[type=checkbox]:checked").count()
        page.locator(".topbar .btn--primary").click()
        page.wait_for_selector(".export__row")
        sync_api.expect(page.locator(".export__row")).to_have_count(ticked, timeout=180_000)
        href = page.locator(".export__row a.btn--accent").first.get_attribute("href")
        assert href and ".mp4?download" in href
        browser.close()

    mp4s = list(out.rglob("*.mp4"))
    assert len(mp4s) == ticked and all(f.stat().st_size > 10_000 for f in mp4s)
    assert any("my-edited-clip" in f.name for f in mp4s)
    assert errors == []
