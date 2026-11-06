"""Check THIRD_PARTY_LICENSES.md against the installed packages' own metadata.

For every row of the "Runtime dependencies" table, the licence written in the table must match the
package's ``License-Expression`` / ``License`` field or its licence classifiers. Packages that are not
installed (optional extras) are skipped; version drift is reported but does not fail.
Usage: uv run python scripts/check_licenses.py
"""

from __future__ import annotations

import importlib.metadata as md
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALIASES = {
    "mit license": "mit",
    "bsd license": "bsd",
    "bsd 3-clause license": "bsd-3-clause",
    "apache software license": "apache-2.0",
}


def _norm(text: str) -> str:
    t = text.strip().lower()
    return ALIASES.get(t, t)


def declared(name: str) -> set[str]:
    meta = md.metadata(name)
    out = set()
    for field in ("License-Expression", "License"):
        value = meta.get(field)
        if value:
            first = value.strip().splitlines()[0]
            out.add(_norm(first))
            out |= {_norm(p) for p in re.split(r"\s+(?:AND|OR)\s+", first)}
    for c in meta.get_all("Classifier") or []:
        if c.startswith("License ::"):
            out.add(_norm(c.split("::")[-1]))
    return out


def rows() -> list[tuple[list[str], list[str], list[str]]]:
    text = (ROOT / "THIRD_PARTY_LICENSES.md").read_text(encoding="utf-8")
    section = text.split("## Runtime dependencies", 1)[1].split("\n## ", 1)[0]
    out = []
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 3 or cells[0] in {"Package", "---"} or set(cells[0]) <= {"-"}:
            continue
        names = [re.sub(r"\s*\(.*\)", "", n).strip() for n in cells[0].split("/")]
        versions = [v.strip() for v in cells[1].split("/")]
        licences = [lic.strip() for lic in cells[2].split("/")]
        if len(licences) == 1:
            licences *= len(names)
        out.append((names, versions, licences))
    return out


def main() -> int:
    problems: list[str] = []
    for names, versions, licences in rows():
        for i, name in enumerate(names):
            try:
                installed = md.version(name)
            except md.PackageNotFoundError:
                print(f"skip  {name} (not installed)")
                continue
            want = licences[i].split(" (")[0].split(" and ")[0].strip()
            have = declared(name)
            ok = _norm(want) in have or (_norm(want).startswith("bsd") and "bsd" in have)
            if not ok:
                problems.append(f"{name}: table says {want!r}, metadata says {sorted(have)}")
            listed = versions[i] if i < len(versions) else ""
            drift = "" if installed in listed else f"  (table lists {listed!r})"
            print(f"{'ok  ' if ok else 'FAIL'}  {name} {installed}: {want}{drift}")
    for p in problems:
        print(f"::error::{p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
