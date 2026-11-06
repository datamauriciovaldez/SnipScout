"""Reproducible README screenshots of a running SnipScout (browser mode).

Usage:
  1. Start the app with a data folder that has one exported project:  snipscout ui --browser --port 8765
  2. python scripts/make_screenshots.py "http://127.0.0.1:8765/?t=TOKEN" [--theme light|dark]
     [--out docs/screenshots] [--gif]
Needs Playwright with Chromium (`--executable` to point at a Chromium binary). `--gif` also records a short
walkthrough (home → results → editor with playback → export) and converts it with ffmpeg (`--ffmpeg`).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    from playwright.sync_api import sync_playwright

    ap = argparse.ArgumentParser()
    ap.add_argument("url", help="Session URL printed by `snipscout ui --browser`")
    ap.add_argument("--theme", default="light", choices=["light", "dark"])
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "screenshots")
    ap.add_argument("--executable")
    ap.add_argument("--lang", default="es-ES")
    ap.add_argument("--gif", action="store_true", help="Also record docs/screenshots/walkthrough.gif")
    ap.add_argument("--ffmpeg", default=shutil.which("ffmpeg") or "ffmpeg")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    base = args.url.split("?")[0]
    with sync_playwright() as p:
        browser = (
            p.chromium.launch(executable_path=args.executable) if args.executable else p.chromium.launch()
        )
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale=args.lang)
        ctx.add_init_script(f"try{{localStorage.setItem('snipscout.theme','{args.theme}')}}catch(e){{}}")
        page = ctx.new_page()
        page.goto(args.url)
        page.wait_for_selector(".home, .welcome")
        projects = page.evaluate("fetch('/api/v1/projects').then(r => r.json())")
        done = next((p["id"] for p in projects if p["status"] == "done"), None)
        if done is None:
            raise SystemExit("Export at least one project first (status 'done').")
        shots = [
            ("home", "#/", ".home"),
            ("results", f"#/proyecto/{done}", ".results .row"),
            ("editor", f"#/proyecto/{done}/clip/c01", ".editor .word"),
            ("export", f"#/proyecto/{done}/exportar", ".export__row"),
        ]
        for name, route, selector in shots:
            page.goto(base + route)
            page.wait_for_selector(selector, timeout=20000)
            page.wait_for_timeout(1000)  # thumbnails and fonts
            page.screenshot(path=str(args.out / f"{name}-{args.theme}.png"))
            print("saved", name)
        if args.gif:
            record_gif(browser, args, base, done)
        browser.close()
    return 0


def record_gif(browser: object, args: argparse.Namespace, base: str, pid: str) -> None:
    """Capture the walkthrough as screenshots at a steady rate, then make a palette-optimised GIF with ffmpeg
    (960 px wide). Frame capture avoids Playwright's separate video ffmpeg download."""
    import time

    fps = 8
    tmp = Path(tempfile.mkdtemp(prefix="snipscout-gif-"))
    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, locale=args.lang)  # type: ignore[attr-defined]
    ctx.add_init_script(f"try{{localStorage.setItem('snipscout.theme','{args.theme}')}}catch(e){{}}")
    page = ctx.new_page()
    frames = [0]

    def hold(ms: int) -> None:
        end = time.monotonic() + ms / 1000
        while time.monotonic() < end:
            t0 = time.monotonic()
            page.screenshot(path=str(tmp / f"f{frames[0]:05d}.png"))
            frames[0] += 1
            time.sleep(max(0.0, 1 / fps - (time.monotonic() - t0)))

    page.goto(args.url)
    page.wait_for_selector(".home, .welcome")
    page.wait_for_timeout(500)
    hold(1200)
    page.goto(f"{base}#/proyecto/{pid}")
    page.wait_for_selector(".results .row")
    page.wait_for_timeout(600)
    hold(1500)
    page.focus("#row-c01")
    for _ in range(2):
        page.keyboard.press("ArrowDown")
        hold(1100)
    page.goto(f"{base}#/proyecto/{pid}/clip/c01")
    page.wait_for_selector(".editor .word")
    page.wait_for_timeout(600)
    hold(600)
    page.keyboard.press("Space")  # play: the active subtitle word follows the voice
    hold(4000)
    page.keyboard.press("Space")
    page.goto(f"{base}#/proyecto/{pid}/exportar")
    page.wait_for_selector(".export__row")
    page.wait_for_timeout(600)
    hold(1800)
    ctx.close()
    out = args.out / "walkthrough.gif"
    vf = (
        "scale=960:-1:flags=lanczos,split[a][b];"
        "[a]palettegen=max_colors=96:stats_mode=diff[p];[b][p]paletteuse=dither=bayer"
    )
    subprocess.run(  # noqa: S603 - fixed arguments, no shell
        [
            args.ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-framerate",
            str(fps),
            "-i",
            str(tmp / "f%05d.png"),
            "-vf",
            vf,
            str(out),
        ],
        check=True,
        timeout=300,
    )
    shutil.rmtree(tmp, ignore_errors=True)
    print("saved", out, f"{frames[0]} frames, {out.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    raise SystemExit(main())
