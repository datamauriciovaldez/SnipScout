"""Text utilities and per-language lexicons (``data/<lang>.json``)."""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA = Path(__file__).parent / "data"
SUPPORTED = ("es", "en")


@lru_cache
def lexicon(lang: str | None) -> dict[str, Any]:
    """Lexicon for ``lang``; unknown languages get the union of all lexicons."""
    base = (lang or "").split("-")[0].lower()
    if base in SUPPORTED:
        data: dict[str, Any] = json.loads((DATA / f"{base}.json").read_text(encoding="utf-8"))
        return data
    merged: dict[str, Any] = {}
    for code in SUPPORTED:
        for key, value in json.loads((DATA / f"{code}.json").read_text(encoding="utf-8")).items():
            if isinstance(value, list):
                merged.setdefault(key, [])
                merged[key] = [*merged[key], *value]
            else:
                merged.setdefault(key, value)
    return merged


def normalize(text: str) -> str:
    """Lowercase, strip accents and punctuation, collapse spaces (for lexicon matching)."""
    t = unicodedata.normalize("NFKD", text.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^\w%]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def count_phrases(text: str, phrases: list[str]) -> int:
    """Count whole-word occurrences of each phrase in ``text`` (both normalized)."""
    padded = f" {normalize(text)} "
    return sum(padded.count(f" {normalize(p)} ") for p in phrases if normalize(p))
