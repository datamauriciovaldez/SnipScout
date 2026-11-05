"""Clip selection entry point: sentences → candidates → score → refine → Clip list."""

from __future__ import annotations

import dataclasses

from snipscout.core import candidates
from snipscout.core.models import Clip, ClipLength, Sentence
from snipscout.core.refine import Window, bounds, select_diverse
from snipscout.core.scoring import ScoringConfig
from snipscout.core.scoring.heuristic import HeuristicScorer
from snipscout.core.text import extract
from snipscout.core.text.vectors import SentenceEncoder, TfidfEncoder


def select_clips(
    sentences: list[Sentence],
    *,
    language: str | None,
    length: ClipLength,
    media_duration: float,
    config: ScoringConfig | None = None,
    encoder: SentenceEncoder | None = None,
    top_k: int | None = None,
) -> list[Clip]:
    if not sentences:
        return []
    cfg = config or ScoringConfig.load()
    texts = [s.text for s in sentences]
    tfidf = TfidfEncoder(language).fit(texts)
    if encoder is not None:
        vectors = encoder.encode(texts)
        cfg = dataclasses.replace(cfg, cohesion_scale=cfg.cohesion_scale_embeddings)
    else:
        vectors = tfidf.encode(texts)
    scorer = HeuristicScorer(sentences, vectors, language, cfg)

    lo, hi = length.bounds
    cands = candidates.windows(sentences, lo, hi)
    if not cands:  # very short media: offer the whole thing as one clip
        cands = [(0, len(sentences))]
    cands = candidates.shortlist(cands, scorer.cheap, cfg.candidates_prefilter)
    scored = {c: scorer.score(*c) for c in cands}
    windows = [Window(i, j, s.score) for (i, j), s in scored.items()]
    picked = select_diverse(windows, vectors, top_k or cfg.top_k, cfg.mmr_lambda, media_duration)
    picked.sort(key=lambda w: -w.score)

    clips: list[Clip] = []
    for rank, w in enumerate(picked, 1):
        s = scored[(w.i, w.j)]
        start, end = bounds(sentences, w.i, w.j, cfg.padding_s, media_duration)
        clips.append(
            Clip(
                id=f"c{rank:02d}",
                rank=rank,
                start=start,
                end=end,
                sentence_start=w.i,
                sentence_end=w.j,
                score=s.score,
                signals=s.signals,
                reasons=s.reasons,
                hook=extract.hook(sentences, w.i, language),
                title=extract.title(sentences, w.i, w.j, vectors, language),
                keywords=tfidf.top_terms(texts[w.i : w.j], k=5),
            )
        )
    return clips
