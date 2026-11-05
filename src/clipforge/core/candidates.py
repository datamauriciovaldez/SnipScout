"""Candidate windows: start and end on sentence boundaries, duration within the requested range."""

from __future__ import annotations

from collections.abc import Callable

from clipforge.core.models import Sentence

TOLERANCE_S = 2.0  # accept windows slightly outside the range; refine() trims/pads later


def windows(sentences: list[Sentence], min_s: float, max_s: float) -> list[tuple[int, int]]:
    """All (i, j) with sentences[i:j] lasting within [min_s - tol, max_s + tol]. ``j`` is exclusive."""
    out: list[tuple[int, int]] = []
    n = len(sentences)
    for i in range(n):
        for j in range(i + 1, n + 1):
            dur = sentences[j - 1].end - sentences[i].start
            if dur > max_s + TOLERANCE_S:
                break
            if dur >= min_s - TOLERANCE_S:
                out.append((i, j))
    return out


def shortlist(
    cands: list[tuple[int, int]], cheap_score: Callable[[int, int], float], limit: int
) -> list[tuple[int, int]]:
    """Keep the ``limit`` best candidates by a cheap score (stable for equal scores)."""
    if len(cands) <= limit:
        return cands
    ranked = sorted(cands, key=lambda c: -cheap_score(*c))
    return ranked[:limit]
