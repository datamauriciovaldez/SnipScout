"""Browser check of the component gallery (design/screens/componentes.html) with the real JS modules.

Checks: no console errors, every icon renders, no raw i18n keys, modal focus trap + Esc + focus return,
toast appears, ARIA states on score/progress/checkbox. Needs Playwright with a Chromium binary.
Usage: python scripts/check_components.py [--executable /path/to/chromium] [--screenshot out.png]
"""

from __future__ import annotations

import argparse
import contextlib
import functools
import http.server
import re
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def serve() -> tuple[http.server.ThreadingHTTPServer, int]:
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            pass

    handler = functools.partial(Quiet, directory=str(ROOT))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def main() -> int:
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright

    ap = argparse.ArgumentParser()
    ap.add_argument("--executable")
    ap.add_argument("--screenshot")
    args = ap.parse_args()
    httpd, port = serve()
    failures: list[str] = []
    with sync_playwright() as p:
        browser = (
            p.chromium.launch(executable_path=args.executable) if args.executable else p.chromium.launch()
        )
        for theme in ("light", "dark"):
            page = browser.new_page(viewport={"width": 1280, "height": 900}, locale="es-ES")
            errors: list[str] = []
            page.on("console", lambda m, e=errors: e.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda exc, e=errors: e.append(str(exc)))
            page.add_init_script(f"try{{localStorage.setItem('snipscout.theme','{theme}')}}catch(e){{}}")
            page.goto(f"http://127.0.0.1:{port}/design/screens/componentes.html")
            page.wait_for_selector("text=Componentes")
            if errors:
                failures.append(f"[{theme}] console errors: {errors}")
            empty_icons = page.evaluate(
                "[...document.querySelectorAll('#icons svg')].filter(s => !s.innerHTML.trim()).length"
            )
            if empty_icons:
                failures.append(f"[{theme}] {empty_icons} icons rendered empty")
            raw = re.findall(
                r"\b(?:components|errors|common|error)\.[a-z_]+(?:\.[a-z_]+)?\b", page.inner_text("body")
            )
            if raw:
                failures.append(f"[{theme}] untranslated keys: {sorted(set(raw))}")
            if theme == "light":
                # Modal: opens, traps focus, Esc closes and returns focus to the opener.
                page.click("#open-modal")
                page.wait_for_selector("[role=dialog]")
                for _ in range(5):
                    page.keyboard.press("Tab")
                inside = page.evaluate(
                    "document.querySelector('[role=dialog]').contains(document.activeElement)"
                )
                page.keyboard.press("Escape")
                page.wait_for_selector("[role=dialog]", state="detached")
                # Focus is returned right after the dialog leaves the DOM; a timeout is reported below.
                with contextlib.suppress(PlaywrightTimeout):
                    page.wait_for_function(
                        "document.activeElement && document.activeElement.id === 'open-modal'", timeout=1000
                    )
                back = page.evaluate("document.activeElement && document.activeElement.id")
                if not inside:
                    failures.append("focus escaped the modal")
                if back != "open-modal":
                    failures.append(f"focus did not return to the opener (got {back!r})")
                page.click("#toast-btn")
                page.wait_for_selector(".toast.is-open")
                checks = page.evaluate("""({
                  high: document.querySelectorAll('.score--high').length,
                  progress: document.querySelector('[role=progressbar]').getAttribute('aria-valuenow'),
                  busy: document.querySelector('.is-loading').getAttribute('aria-busy'),
                  checkbox: document.querySelector('#cb').checked,
                })""")
                if checks != {"high": 1, "progress": "36", "busy": "true", "checkbox": True}:
                    failures.append(f"aria/state mismatch: {checks}")
                if args.screenshot:
                    page.screenshot(path=args.screenshot, full_page=True)
            page.close()
        browser.close()
    httpd.shutdown()
    for f in failures:
        print("FAIL", f)
    print("components ok" if not failures else f"{len(failures)} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
