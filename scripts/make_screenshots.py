"""Reproducible README screenshots of a running SnipScout (browser mode).

Usage:
  1. Start the app with a data folder that has one exported project:  snipscout ui --browser --port 8765
  2. python scripts/make_screenshots.py "http://127.0.0.1:8765/?t=TOKEN" [--theme light|dark]
     [--out docs/screenshots]
Needs Playwright with Chromium (`--executable` to point at a Chromium binary).
"""

from __future__ import annotations

import argparse
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
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
