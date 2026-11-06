"""Accessibility audit of the running app (every screen, both themes).

Checks per screen: axe-core WCAG 2.1 A/AA rules (if --axe points to axe.min.js), visible interactive
targets >= 40 px incl. a ::before hit area (inline targets and checkboxes inside a tall label are exempt), a
keyboard Tab walk (every stop visible, with a focus indicator, no trap) and 200 % zoom (no horizontal
page scroll at 720 px CSS width). Needs Playwright with Chromium and an app server with at least one
analysed project (status "done").
Usage: python scripts/check_a11y.py --url "http://127.0.0.1:PORT/?t=TOKEN" [--axe axe.min.js]
       [--executable /path/to/chromium] [--screens out_dir]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

MIN_TARGET = 40
TAB_STOPS = 60

DESCRIBE_JS = """window.describe = (el) => {
  const name = (el.getAttribute("aria-label") || el.textContent || "").trim().slice(0, 30);
  return `${el.tagName.toLowerCase()}.${[...el.classList].join(".")} "${name}"`;
}"""

AXE_JS = "axe.run(document, {runOnly: {type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})"

TARGETS_JS = """(min) => {
  const sel = "button, a[href], input, select, textarea, [role=button], [role=slider], "
    + "[tabindex]:not([tabindex='-1'])";
  const out = [];
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    if (!r.width || !r.height || st.visibility === "hidden") continue;
    if (el.closest("[aria-hidden=true],[inert]")) continue;
    if (el.matches(".skip-link")) continue;
    if (st.display === "inline") continue;  // inline target inside a sentence (WCAG 2.5.8 inline exception)
    if (el.matches("input[type=checkbox],input[type=radio],input[type=file]") && el.closest("label")) {
      const lr = el.closest("label").getBoundingClientRect();
      if (lr.height >= min) continue;
    }
    const hit = getComputedStyle(el, "::before");  // compact controls extend their hit area with ::before
    const extends_ = hit.content !== "none" && hit.position === "absolute";
    const w = Math.max(r.width, extends_ ? parseFloat(hit.width) || 0 : 0);
    const h = Math.max(r.height, extends_ ? parseFloat(hit.height) || 0 : 0);
    if (w < min - 0.5 || h < min - 0.5)
      out.push(`${describe(el)} ${Math.round(w)}x${Math.round(h)}`);
  }
  return out;
}"""

FOCUS_JS = """() => {
  const el = document.activeElement;
  if (!el || el === document.body) return null;
  const r = el.getBoundingClientRect();
  const st = getComputedStyle(el);
  const ring = (st.outlineStyle !== "none" && parseFloat(st.outlineWidth) > 0) || st.boxShadow !== "none";
  const vis = r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0 && r.top < innerHeight + 4000;
  return { id: describe(el), ring, vis };
}"""


def main() -> int:
    from playwright.sync_api import sync_playwright

    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--axe")
    ap.add_argument("--executable")
    ap.add_argument("--screens")
    args = ap.parse_args()
    base = args.url.split("?")[0]
    axe = Path(args.axe).read_text(encoding="utf-8") if args.axe else None
    problems: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=args.executable or None)
        boot = browser.new_context()
        page = boot.new_page()
        page.goto(args.url)
        page.wait_for_selector("#main")
        cookies = boot.cookies()
        projects = page.evaluate("fetch('/api/v1/projects').then(r => r.json())")
        done = next((x for x in projects if x["status"] == "done"), None)
        if done is None:
            print("no analysed project found", file=sys.stderr)
            return 2
        pid = done["id"]
        screens = {
            "welcome": ("#/bienvenida", ".welcome, #main"),
            "home": ("#/", ".home"),
            "projects": ("#/proyectos", ".projects__row"),
            "settings": ("#/ajustes", ".disk__head"),
            "results": (f"#/proyecto/{pid}", ".results, #main"),
            "editor": (f"#/proyecto/{pid}/clip/c01", ".editor .word"),
            "export": (f"#/proyecto/{pid}/exportar", "#main"),
            "notfound": ("#/nada", "#main"),
        }
        for theme in ("light", "dark"):
            for zoom, size in (("100", (1440, 900)), ("200", (720, 450))):
                ctx = browser.new_context(viewport={"width": size[0], "height": size[1]}, locale="es-ES")
                ctx.add_cookies(cookies)
                ctx.add_init_script(f"localStorage.setItem('snipscout.theme', '{theme}')")
                ctx.add_init_script(DESCRIBE_JS)
                pg = ctx.new_page()
                errors: list[str] = []
                pg.on("console", lambda m, e=errors: e.append(m.text) if m.type == "error" else None)
                pg.on("pageerror", lambda exc, e=errors: e.append(str(exc)))
                for name, (hash_, ready) in screens.items():
                    tag = f"[{theme} {zoom}% {name}]"
                    pg.goto(f"{base}{hash_}")
                    pg.wait_for_selector(ready, timeout=15000)
                    pg.wait_for_timeout(700)
                    if zoom == "200":
                        overflow = pg.evaluate("document.documentElement.scrollWidth - innerWidth")
                        if overflow > 1:
                            problems.append(f"{tag} horizontal scroll {overflow}px")
                        if args.screens and theme == "light":
                            pg.screenshot(path=f"{args.screens}/a11y-{name}-200.png")
                        continue
                    if args.screens:
                        pg.screenshot(path=f"{args.screens}/a11y-{name}-{theme}.png")
                    problems += [f"{tag} small target {t}" for t in pg.evaluate(TARGETS_JS, MIN_TARGET)]
                    if axe:
                        pg.add_script_tag(content=axe)
                        res = pg.evaluate(AXE_JS)
                        for v in res["violations"]:
                            nodes = "; ".join(n["target"][0] if n["target"] else "?" for n in v["nodes"][:4])
                            problems.append(f"{tag} axe {v['id']} ({v['impact']}): {nodes}")
                    # Keyboard walk from the top of the page.
                    pg.evaluate("document.activeElement && document.activeElement.blur()")
                    seen: list[str] = []
                    for _ in range(TAB_STOPS):
                        pg.keyboard.press("Tab")
                        info = pg.evaluate(FOCUS_JS)
                        if info is None:
                            continue
                        if not info["vis"]:
                            problems.append(f"{tag} focus on invisible {info['id']}")
                        elif not info["ring"]:
                            problems.append(f"{tag} no focus ring {info['id']}")
                        if seen and info["id"] == seen[-1]:
                            problems.append(f"{tag} focus stuck on {info['id']}")
                            break
                        if info["id"] in seen[:1]:
                            break  # wrapped around
                        seen.append(info["id"])
                    if len(seen) < 3:
                        problems.append(f"{tag} only {len(seen)} tab stops")
                problems += [f"[{theme} {zoom}%] console: {e}" for e in errors]
                ctx.close()
        browser.close()

    unique = list(dict.fromkeys(problems))
    print(json.dumps(unique, indent=1, ensure_ascii=False) if unique else "a11y: no problems found")
    return 1 if unique else 0


if __name__ == "__main__":
    sys.exit(main())
