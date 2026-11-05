# ClipForge design system — notes

**Source of truth:** `design/reference/referencia-resultados{,-oscuro}.html` (approved). Everything else derives from it.

**Tokens (`css/tokens.css`, the only colour source).** Semantic names; themes change values only.
- Light (paper): `--bg #F1F0EB`, `--panel #FAF9F6`, `--line #D9D7CE`, `--text #17171A`, `--text-2 #58564F`, `--text-3 #6F6D65`, `--accent #D93A12`, `--ok #2F6B4F`.
- Dark (warm graphite): `--bg #151513`, `--panel #1C1C1A`, `--line #34332E`, `--text #EDEBE4`, `--accent #FF6A3D`. Primary button turns bone; text on accent is `#17120F`.
- Added for AA (checked by `scripts/check_contrast.py`, both themes):
  - `--accent-text #B5300C`: the light accent is 4.0:1 as small text, so text uses this darker shade; fills keep `#D93A12`.
  - `--line-strong`: control borders need 3:1; `--line` stays for 1px separators.
  - `--subtitle-active-text`: white on `#FF6A3D` is 2.85:1, so dark uses `#17120F` (as the reference does).
- Data-viz colours (score track, wave in/out, progress) are tokens too, with per-theme values.

**Accent is rationed:** high scores (≥85), active subtitle word, wave markers/handles, active row bar, Download.
Focus rings, drop "release here", busy dots, edited words and disk bars use ink, never the accent.

**Type:** IBM Plex Sans 400–700 (UI, titles 30/600, −.02em) + IBM Plex Mono 400/500 (times, numbers, labels 11px caps .08em,
shortcuts), tabular numbers. Vendored woff2 (OFL) in `fonts/`, no CDN.

**Shape:** radii 3/4/6px, 1px rules, rows separated by lines, no shadows except toast/modal/tooltip. 18px square checkboxes.
Thumbnails: muted gradient + SVG fractal-noise grain (`.thumb::after`).

**Theme switching:** `js/theme.js` runs in `<head>` before CSS paints; `localStorage["clipforge.theme"]` = light|dark|system
(try/catch); system = no `data-theme`. `index.html` also pushes the theme into its iframe via `postMessage`.
Theme change animates colour only (150ms); other motion is 120/220ms on transform/opacity; reduced motion zeroes durations.

**Screens:** `screens/index.html` (navigator + theme + 1440×900 / 1000×680). Each screen has a hash for states:
`resultados#vacio|#cargando`, `inicio#arrastrando`, `primer-arranque#paso1|#paso3`.
Checks: `scripts/check_contrast.py` (AA) and a DOM overflow check at both sizes (no overflow).
