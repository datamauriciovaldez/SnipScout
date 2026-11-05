"""Clip scoring. ``HeuristicScorer`` is the built-in, explainable, LLM-free scorer."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

WEIGHTS_FILE = Path(__file__).parent / "weights.toml"


@dataclass(frozen=True)
class ScoringConfig:
    weights: dict[str, float]
    band_low: float = 1.8
    band_high: float = 3.8
    inner_pause_s: float = 1.2
    candidates_prefilter: int = 400
    top_k: int = 12
    mmr_lambda: float = 0.75
    padding_s: float = 0.15
    reason_threshold: float = 0.6
    cohesion_scale: float = 0.04
    cohesion_scale_embeddings: float = 0.35
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None = None) -> ScoringConfig:
        data = tomllib.loads((path or WEIGHTS_FILE).read_text(encoding="utf-8"))
        pace, sel = data.get("pace", {}), data.get("selection", {})
        return cls(
            weights={k: float(v) for k, v in data["weights"].items()},
            band_low=float(pace.get("band_low", 1.8)),
            band_high=float(pace.get("band_high", 3.8)),
            inner_pause_s=float(pace.get("inner_pause_s", 1.2)),
            candidates_prefilter=int(sel.get("candidates_prefilter", 400)),
            top_k=int(sel.get("top_k", 12)),
            mmr_lambda=float(sel.get("mmr_lambda", 0.75)),
            padding_s=float(sel.get("padding_s", 0.15)),
            reason_threshold=float(sel.get("reason_threshold", 0.6)),
            cohesion_scale=float(data.get("cohesion", {}).get("scale_tfidf", 0.04)),
            cohesion_scale_embeddings=float(data.get("cohesion", {}).get("scale_embeddings", 0.35)),
        )
