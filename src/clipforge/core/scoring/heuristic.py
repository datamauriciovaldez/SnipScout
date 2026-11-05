"""HeuristicScorer: seven explainable signals in [0, 1], combined with weights from weights.toml."""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from clipforge.core.models import Sentence
from clipforge.core.scoring import ScoringConfig
from clipforge.core.text import count_phrases, lexicon, normalize
from clipforge.core.text.vectors import Matrix

_DIGIT = re.compile(r"\d")
_TERMINAL = (".", "!", "?", "…")


def _starts_with(text: str, phrases: list[str]) -> bool:
    t = f"{normalize(text)} "
    return any(t.startswith(f"{normalize(p)} ") for p in phrases if normalize(p))


def _ends_with(text: str, phrases: list[str]) -> bool:
    t = f" {normalize(text)}"
    return any(t.endswith(f" {normalize(p)}") for p in phrases if normalize(p))


def _clamp(x: float) -> float:
    return float(min(1.0, max(0.0, x)))


@dataclass
class Scored:
    score: float  # 0-100
    signals: dict[str, float]
    reasons: list[str]


class HeuristicScorer:
    def __init__(
        self,
        sentences: list[Sentence],
        vectors: Matrix,
        language: str | None,
        config: ScoringConfig | None = None,
    ) -> None:
        self.s = sentences
        self.v = vectors
        self.lex = lexicon(language)
        self.cfg = config or ScoringConfig.load()
        rms = [x.rms_mean for x in sentences if x.rms_mean > 0]
        self.rms_median = float(np.median(rms)) if rms else 0.0

    # -- individual signals ------------------------------------------------------------------------
    def hook(self, i: int) -> tuple[float, list[str]]:
        first = self.s[i].text
        opening = " ".join(first.split()[:10])
        reasons: list[str] = []
        score = 0.0
        if (
            first.rstrip().endswith("?")
            or first.lstrip().startswith("¿")
            or _starts_with(first, self.lex["question_starters"])
            and "?" in first
        ):
            score += 0.6
            reasons.append("question_hook")
        if _DIGIT.search(opening) or count_phrases(opening, self.lex["numbers"]):
            score += 0.35
            reasons.append("number_hook")
        strong = count_phrases(opening, self.lex["emphasis"]) + count_phrases(opening, self.lex["contrast"])
        if strong:
            score += min(0.5, 0.3 * strong)
        if count_phrases(opening, self.lex["address"]):
            score += 0.15
        if score >= 0.6 and not reasons:
            reasons.append("strong_hook")
        return _clamp(score), reasons

    def pace(self, i: int, j: int) -> float:
        span = self.s[i:j]
        dur = span[-1].end - span[0].start
        words = sum(x.word_end - x.word_start for x in span)
        wps = words / max(dur, 1e-3)
        lo, hi = self.cfg.band_low, self.cfg.band_high
        band = 1.0 if lo <= wps <= hi else max(0.0, 1 - (lo - wps if wps < lo else wps - hi) / lo)
        long_pauses = sum(max(0.0, x.pause_after - self.cfg.inner_pause_s) for x in span[:-1])
        fillers = sum(x.fillers for x in span) / max(words, 1)
        return _clamp(band - 0.15 * long_pauses - 3.0 * fillers)

    def energy(self, i: int, j: int) -> float:
        span = self.s[i:j]
        if self.rms_median <= 0:
            return 0.5  # no audio features available: neutral
        dyn = float(np.mean([x.rms_variation for x in span]))  # ~0.3 flat ... ~1.0 lively
        loud = float(np.mean([x.rms_mean for x in span])) / self.rms_median
        return _clamp(0.6 * _clamp((dyn - 0.3) / 0.7) + 0.4 * _clamp(loud - 0.5))

    def cohesion(self, i: int, j: int) -> float:
        if j - i < 2 or self.v.shape[1] == 0:
            return 0.5
        block = self.v[i:j]
        n = j - i
        # Mean pairwise cosine (diagonal excluded). Unlike similarity-to-centroid, it is ~0 for
        # unrelated sentences regardless of how many there are.
        pairwise = (float((block @ block.T).sum()) - float(np.einsum("ij,ij->", block, block))) / (n * n - n)
        return _clamp(pairwise / self.cfg.cohesion_scale)

    def closure(self, j: int) -> float:
        last = self.s[j - 1]
        text = last.text.rstrip()
        score = 0.0
        if text.endswith(_TERMINAL):
            score += 0.45
        if text.endswith("?"):
            score -= 0.3  # ends on an open question
        if count_phrases(text, self.lex["closers"]):
            score += 0.4
        if last.pause_after >= 0.5 or j == len(self.s):
            score += 0.15
        if _ends_with(text.rstrip(".!?…,"), self.lex["dangling_ends"]):
            score -= 0.5
        return _clamp(score)

    def autonomy(self, i: int) -> float:
        first = self.s[i].text
        score = 1.0
        if _starts_with(first, self.lex["dangling_starts"]):
            score -= 0.7
        elif _starts_with(first, self.lex["weak_starts"]):
            score -= 0.3
        if i > 0 and self.s[i].pause_before < 0.15:
            score -= 0.15  # starts in the middle of a fluent stretch
        return _clamp(score)

    def confidence(self, i: int, j: int) -> float:
        return _clamp(float(np.mean([x.confidence for x in self.s[i:j]])))

    # -- combined ----------------------------------------------------------------------------------
    def cheap(self, i: int, j: int) -> float:
        """Fast pre-score used to shortlist candidates (opening + ending + autonomy)."""
        return self.hook(i)[0] * 3 + self.closure(j) * 2.5 + self.autonomy(i) * 2

    def score(self, i: int, j: int) -> Scored:
        hook, hook_reasons = self.hook(i)
        signals = {
            "hook": hook,
            "pace": self.pace(i, j),
            "energy": self.energy(i, j),
            "cohesion": self.cohesion(i, j),
            "closure": self.closure(j),
            "autonomy": self.autonomy(i),
            "confidence": self.confidence(i, j),
        }
        w = self.cfg.weights
        total = sum(w.get(k, 0.0) * v for k, v in signals.items()) / max(sum(w.values()), 1e-9)
        th = self.cfg.reason_threshold
        reasons = list(hook_reasons) if hook >= 0.5 else []
        for key, reason in (
            ("energy", "high_energy"),
            ("cohesion", "coherent_topic"),
            ("closure", "strong_ending"),
            ("pace", "good_pace"),
        ):
            if signals[key] >= th:
                reasons.append(reason)
        if signals["autonomy"] >= 0.99 and len(reasons) < 4:
            reasons.append("self_contained")
        return Scored(round(total * 100, 1), {k: round(v, 3) for k, v in signals.items()}, reasons[:4])
