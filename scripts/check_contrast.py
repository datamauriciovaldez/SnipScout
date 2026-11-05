"""Check WCAG AA contrast for every text/background pair defined in design/css/tokens.css, in both themes.

Normal text needs 4.5:1, large/bold text and UI components (borders, bars, focus) need 3:1.
Exit code 1 if any pair fails.  Usage: uv run python scripts/check_contrast.py [path/to/tokens.css]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKENS = ROOT / "design" / "css" / "tokens.css"

# (foreground, background, minimum ratio, what it is)
PAIRS: list[tuple[str, str, float, str]] = [
    *[(fg, bg, 4.5, "body text") for fg in ("text", "text-2", "text-3") for bg in ("bg", "panel", "sunken")],
    ("accent-text", "bg", 4.5, "accent as small text"),
    ("accent-text", "panel", 4.5, "accent as small text"),
    ("on-accent", "accent", 4.5, "text on Download button / active word"),
    ("btn-primary-text", "btn-primary-bg", 4.5, "primary button"),
    ("check-mark", "check-bg", 3.0, "checkbox tick"),
    ("ok", "bg", 4.5, "status text"),
    ("ok", "panel", 4.5, "status text"),
    ("danger", "bg", 4.5, "error text"),
    ("danger", "panel", 4.5, "error text"),
    ("warn", "panel", 4.5, "warning text"),
    ("text-inverse", "text", 4.5, "tooltip / toast"),
    ("line-strong", "bg", 3.0, "control border"),
    ("line-strong", "panel", 3.0, "control border"),
    ("focus", "bg", 3.0, "focus ring"),
    ("focus", "panel", 3.0, "focus ring"),
    ("score-high", "score-track", 3.0, "score bar (high)"),
    ("score-low", "score-track", 3.0, "score bar (low)"),
    ("progress-fill", "progress-track", 3.0, "progress bar"),
    ("wave-in", "panel", 3.0, "waveform inside clip"),
    ("subtitle-active-text", "accent", 3.0, "active subtitle word (large bold)"),
]


def _hex(value: str) -> tuple[float, float, float]:
    v = value.strip().lstrip("#")
    if len(v) == 8:  # ignore alpha for solid tokens that carry an alpha suffix
        v = v[:6]
    return tuple(int(v[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def _lum(rgb: tuple[float, float, float]) -> float:
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in rgb]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def ratio(a: str, b: str) -> float:
    la, lb = sorted((_lum(_hex(a)), _lum(_hex(b))), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def parse(css: str) -> dict[str, dict[str, str]]:
    """Return {'light': tokens, 'dark': tokens}.

    Light = the first bare :root block; dark = the :root[data-theme="dark"] block."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    decl = re.compile(r"--([\w-]+)\s*:\s*(#[0-9A-Fa-f]{6,8})\s*;")
    light_block = re.search(r":root\s*\{(.*?)\n\}", css, flags=re.S)
    dark_block = re.search(r':root\[data-theme="dark"\]\s*\{(.*?)\n\}', css, flags=re.S)
    if not light_block or not dark_block:
        raise SystemExit("tokens.css: could not find the light :root block or the dark block")
    light = dict(decl.findall(light_block.group(1)))
    dark = {**light, **dict(decl.findall(dark_block.group(1)))}
    return {"light": light, "dark": dark}


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else TOKENS
    themes = parse(path.read_text(encoding="utf-8"))
    failures = 0
    for theme, tok in themes.items():
        print(f"\n{theme.upper()}")
        for fg, bg, minimum, what in PAIRS:
            if fg not in tok or bg not in tok:
                print(f"  MISSING  --{fg} / --{bg}")
                failures += 1
                continue
            r = ratio(tok[fg], tok[bg])
            ok = r >= minimum
            failures += not ok
            print(f"  {'ok  ' if ok else 'FAIL'} {r:5.2f} (≥{minimum})  --{fg} on --{bg}  [{what}]")
    print(f"\n{'All pairs pass AA.' if not failures else f'{failures} pair(s) fail.'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
