"""Sentence vectors for topic cohesion and diversity.

Default: TF-IDF computed with numpy (no extra dependency). Optional: local multilingual
embeddings via ``fastembed`` when the user has downloaded them (see ``EmbeddingEncoder``).
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Protocol

import numpy as np
import numpy.typing as npt

from clipforge.core.text import lexicon, normalize

Matrix = npt.NDArray[np.float32]


class SentenceEncoder(Protocol):
    def encode(self, texts: list[str]) -> Matrix: ...


def tokenize(text: str, stopwords: set[str]) -> list[str]:
    return [t for t in normalize(text).split() if len(t) > 2 and t not in stopwords and not t.isdigit()]


class TfidfEncoder:
    """Fit on all sentences of a transcript; rows are L2-normalised."""

    def __init__(self, language: str | None) -> None:
        self.stopwords = set(lexicon(language).get("stopwords", []))
        self.vocab: dict[str, int] = {}
        self.idf: npt.NDArray[np.float64] = np.zeros(0)

    def fit(self, texts: list[str]) -> TfidfEncoder:
        docs = [set(tokenize(t, self.stopwords)) for t in texts]
        df: Counter[str] = Counter()
        for d in docs:
            df.update(d)
        self.vocab = {w: i for i, w in enumerate(sorted(df))}
        n = max(len(texts), 1)
        self.idf = np.array([math.log((1 + n) / (1 + df[w])) + 1 for w in sorted(df)])
        return self

    def encode(self, texts: list[str]) -> Matrix:
        m = np.zeros((len(texts), len(self.vocab)), dtype=np.float32)
        for r, t in enumerate(texts):
            for w, c in Counter(tokenize(t, self.stopwords)).items():
                j = self.vocab.get(w)
                if j is not None:
                    m[r, j] = c * self.idf[j]
        return l2_normalize(m)

    def top_terms(self, texts: list[str], k: int = 5) -> list[str]:
        """Highest TF-IDF terms of the concatenated texts (keywords)."""
        v = self.encode([" ".join(texts)])[0]
        inv = {i: w for w, i in self.vocab.items()}
        return [inv[i] for i in np.argsort(-v)[:k] if v[i] > 0]


def l2_normalize(m: Matrix) -> Matrix:
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (m / norms).astype(np.float32)


class EmbeddingEncoder:
    """Optional local embeddings (``pip install clipforge[embeddings]`` + one-time model download)."""

    MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

    def __init__(self, cache_dir: str) -> None:
        from fastembed import TextEmbedding  # optional dependency

        self._model = TextEmbedding(self.MODEL, cache_dir=cache_dir)

    def encode(self, texts: list[str]) -> Matrix:
        return l2_normalize(np.array(list(self._model.embed(texts, batch_size=64)), dtype=np.float32))
