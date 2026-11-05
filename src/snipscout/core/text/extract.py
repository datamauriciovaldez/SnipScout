"""Extractive (not generative) hooks, titles and keywords. Nothing here invents text."""

from __future__ import annotations

import re

import numpy as np

from snipscout.core.models import Sentence
from snipscout.core.text import lexicon, normalize
from snipscout.core.text.vectors import Matrix

HOOK_MAX = 80
TITLE_MAX = 70


def _strip_leading_fillers(text: str, fillers: list[str]) -> str:
    changed = True
    while changed:
        changed = False
        for f in sorted(fillers, key=len, reverse=True):
            m = re.match(rf"^\s*{re.escape(f)}\b[\s,.…]*", text, flags=re.IGNORECASE)
            if m and normalize(text[: m.end()]) == normalize(f):
                text = text[m.end() :]
                changed = True
    return text.strip()


def trim_clean(text: str, limit: int) -> str:
    """Cut at a word boundary under ``limit`` chars and add an ellipsis if cut."""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:—-")
    return cut + "…"


def _capitalize(text: str) -> str:
    for k, ch in enumerate(text):
        if ch.isalpha():
            return text[:k] + ch.upper() + text[k + 1 :]
    return text


def hook(sentences: list[Sentence], i: int, language: str | None) -> str:
    fillers = lexicon(language).get("fillers", [])
    return _capitalize(trim_clean(_strip_leading_fillers(sentences[i].text, fillers), HOOK_MAX))


def title(sentences: list[Sentence], i: int, j: int, vectors: Matrix, language: str | None) -> str:
    """The sentence closest to the clip's centroid, cleaned (fillers, trailing period)."""
    fillers = lexicon(language).get("fillers", [])
    best = i
    if j - i > 1 and vectors.shape[1]:
        block = vectors[i:j]
        centroid = block.mean(axis=0)
        sims = block @ centroid
        # Prefer sentences of reasonable length for a title.
        lengths = np.array([len(s.text) for s in sentences[i:j]])
        sims = sims - 0.002 * np.abs(lengths - 50)
        best = i + int(np.argmax(sims))
    text = _strip_leading_fillers(sentences[best].text, fillers).rstrip(" .…")
    return _capitalize(trim_clean(text, TITLE_MAX))
