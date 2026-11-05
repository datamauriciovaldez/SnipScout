"""Turn scored windows into final clips: padding, no overlaps, diversity (MMR)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from snipscout.core.models import Sentence
from snipscout.core.text.vectors import Matrix


@dataclass
class Window:
    i: int
    j: int  # exclusive
    score: float  # 0-100


def bounds(
    sentences: list[Sentence], i: int, j: int, padding: float, media_duration: float
) -> tuple[float, float]:
    """Clip times: first word start / last word end (silence already excluded) plus padding,
    never reaching into the neighbouring sentences."""
    start = sentences[i].start - padding
    end = sentences[j - 1].end + padding
    if i > 0:
        start = max(start, sentences[i - 1].end + 0.02)
    if j < len(sentences):
        end = min(end, sentences[j].start - 0.02)
    return round(max(0.0, start), 3), round(min(media_duration, end), 3)


def _overlap(a: Window, b: Window) -> bool:
    return a.i < b.j and b.i < a.j


def _centroid(vectors: Matrix, w: Window) -> np.ndarray:
    c = vectors[w.i : w.j].mean(axis=0)
    n = float(np.linalg.norm(c))
    return c / n if n else c


def select_diverse(
    windows: list[Window], vectors: Matrix, k: int, lam: float, total_s: float
) -> list[Window]:
    """Maximal Marginal Relevance: score vs. similarity (topic + time) to already-picked clips.
    Overlapping windows are never selected together."""
    pool = sorted(windows, key=lambda w: -w.score)
    picked: list[Window] = []
    cents: list[np.ndarray] = []
    has_vec = vectors.shape[1] > 0
    while pool and len(picked) < k:
        best_idx, best_val = -1, -1e9
        for idx, w in enumerate(pool):
            if any(_overlap(w, p) for p in picked):
                continue
            sim = 0.0
            if picked:
                c = _centroid(vectors, w) if has_vec else None
                for p, pc in zip(picked, cents, strict=True):
                    topic = float(c @ pc) if c is not None else 0.0
                    gap = abs(w.i - p.i) / max(len(vectors), 1)
                    temporal = max(0.0, 1.0 - gap * 10)  # near in the video = similar
                    sim = max(sim, 0.7 * topic + 0.3 * temporal)
            val = lam * (w.score / 100) - (1 - lam) * sim
            if val > best_val:
                best_idx, best_val = idx, val
        if best_idx < 0:
            break
        chosen = pool.pop(best_idx)
        picked.append(chosen)
        cents.append(_centroid(vectors, chosen) if has_vec else np.zeros(0))
    return picked
