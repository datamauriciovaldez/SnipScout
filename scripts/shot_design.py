"""Screenshot design screens. Usage: shot_design.py OUT_DIR WIDTHxHEIGHT file.html[@theme][#hash] ...

theme = light | dark (sets html[data-theme] before paint via localStorage-free injection)."""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> int:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    w, h = (int(x) for x in sys.argv[2].split("x"))
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        for spec in sys.argv[3:]:
            target, _, theme = spec.partition("@")
            theme, _, frag = theme.partition("#") if theme else ("", "", "")
            if "#" in target:
                target, frag = target.split("#", 1)
            page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
            errors: list[str] = []
            page.on("console", lambda m, errs=errors: errs.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e, errs=errors: errs.append(str(e)))
            if theme:
                page.add_init_script(f"try{{localStorage.setItem('snipscout.theme','{theme}')}}catch(e){{}}")
            page.goto(Path(target).resolve().as_uri() + (f"#{frag}" if frag else ""))
            page.wait_for_timeout(400)
            name = f"{Path(target).stem}{'-' + frag if frag else ''}-{theme or 'auto'}-{w}.png"
            page.screenshot(path=str(out / name))
            print(name, "errors:" if errors else "", "; ".join(errors[:3]))
            page.close()
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
