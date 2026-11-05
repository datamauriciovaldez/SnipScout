"""Autonomy guard: the shipped code must never depend on paid AI APIs or API keys,
and ``core`` must not import the UI layers."""

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "clipforge"
FORBIDDEN = re.compile(
    r"\b(openai|cohere|mistralai|generativeai)\b|sk-[A-Za-z0-9]{20,}|api[_-]?key", re.IGNORECASE
)


def _source_files() -> list[Path]:
    return [p for p in SRC.rglob("*") if p.is_file() and p.suffix in {".py", ".js", ".html", ".json", ".css"}]


def test_no_forbidden_references_in_src() -> None:
    hits = [
        f"{p.relative_to(SRC)}:{n}: {line.strip()}"
        for p in _source_files()
        for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1)
        if FORBIDDEN.search(line)
    ]
    assert not hits, "Forbidden references in src/:\n" + "\n".join(hits)


def test_core_does_not_import_ui_layers() -> None:
    bad = re.compile(r"^\s*(from|import)\s+clipforge\.(web|cli|desktop)\b", re.MULTILINE)
    offenders = [
        str(p.relative_to(SRC)) for p in (SRC / "core").rglob("*.py") if bad.search(p.read_text("utf-8"))
    ]
    assert not offenders, offenders
