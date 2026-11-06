"""CI smoke test of the real app: start the local server, call the API, open screens in Chromium.

Uses a throw-away data folder (no models, no projects), so it exercises the first-run path:
GET /api/v1/system/status with the session cookie, then Welcome, Settings, Projects (empty) and the
404 screen in light and dark themes. Fails on any console error. Screenshots go to --out.
Usage: uv run --with playwright python scripts/smoke_ui.py --out smoke-shots [--executable chromium]
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
import tempfile
from pathlib import Path

I18N_SECTIONS = {"nav", "home", "settings", "welcome", "projects", "common", "errors"}
SCREENS = {
    "welcome": ("#/bienvenida", ".welcome, #main"),
    "settings": ("#/ajustes", ".settings"),
    "projects": ("#/proyectos", ".projects"),
    "notfound": ("#/nada", "#main"),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="smoke-shots")
    ap.add_argument("--executable")
    args = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="snipscout-smoke-"))
    dirs = {"SNIPSCOUT_DATA_DIR": "data", "SNIPSCOUT_CACHE_DIR": "cache", "SNIPSCOUT_OUTPUT_DIR": "out"}
    for var, sub in dirs.items():
        os.environ[var] = str(tmp / sub)

    import httpx
    from playwright.sync_api import sync_playwright

    from snipscout.core.binaries import resolve_ffmpeg
    from snipscout.core.errors import FfmpegMissingError
    from snipscout.core.storage import ProjectStore
    from snipscout.desktop import start_server
    from snipscout.web.app import Context

    try:
        binaries = resolve_ffmpeg()
    except FfmpegMissingError:
        binaries = None  # the UI must still start and explain the problem
    ctx = Context(ProjectStore(), binaries, secrets.token_urlsafe(32))
    server, port = start_server(ctx)
    base = f"http://127.0.0.1:{port}"
    problems: list[str] = []
    try:
        with httpx.Client(base_url=base, trust_env=False, timeout=15) as http:
            if http.get("/api/v1/system/status").status_code != 401:
                problems.append("API answered without a session")
            http.get(f"/?t={ctx.token}")
            status = http.get("/api/v1/system/status")
            status.raise_for_status()
            info = status.json()
            print(f"status: first_run={info.get('first_run')} offline={info.get('offline')}")

        Path(args.out).mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=args.executable or None)
            for theme in ("light", "dark"):
                page = browser.new_page(viewport={"width": 1280, "height": 800}, locale="en-US")
                page.add_init_script(f"localStorage.setItem('snipscout.theme', '{theme}')")
                errors: list[str] = []
                page.on("console", lambda m, e=errors: e.append(m.text) if m.type == "error" else None)
                page.on("pageerror", lambda exc, e=errors: e.append(str(exc)))
                page.goto(f"{base}/?t={ctx.token}")
                page.wait_for_selector("#main")
                for name, (hash_, ready) in SCREENS.items():
                    page.goto(f"{base}/{hash_}")
                    page.wait_for_selector(ready, timeout=15000)
                    page.wait_for_timeout(400)
                    raw = page.evaluate("document.body.innerText.match(/\\b[a-z_]+\\.[a-z_]+\\b/g) || []")
                    keys = [k for k in raw if k.split(".")[0] in I18N_SECTIONS]
                    if keys:
                        problems.append(f"{theme}/{name}: untranslated keys {keys[:3]}")
                    page.screenshot(path=f"{args.out}/{name}-{theme}.png")
                problems += [f"{theme}: console: {e}" for e in errors]
                page.close()
            browser.close()
    finally:
        server.should_exit = True
    for p in problems:
        print(f"::error::{p}")
    print("smoke: ok" if not problems else f"smoke: {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
