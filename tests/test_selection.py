from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

from snipscout.core import candidates
from snipscout.core.models import ClipLength, Sentence, Word
from snipscout.core.refine import Window, bounds, select_diverse
from snipscout.core.scoring import ScoringConfig
from snipscout.core.scoring.heuristic import HeuristicScorer
from snipscout.core.segment import segment
from snipscout.core.select import select_clips
from snipscout.core.text import extract, lexicon
from snipscout.core.text.vectors import TfidfEncoder

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import eval_scoring  # noqa: E402


def _sentences(texts: list[str], gap: float = 0.7, wps: float = 2.6) -> list[Sentence]:
    words: list[Word] = []
    t = 0.0
    for text in texts:
        for tok in text.split():
            words.append(Word(text=tok, start=t, end=t + 0.3, prob=0.9))
            t += 1 / wps
        t += gap
    return segment(words, language="es")


def _scorer(sents: list[Sentence], lang: str = "es") -> HeuristicScorer:
    texts = [s.text for s in sents]
    return HeuristicScorer(sents, TfidfEncoder(lang).fit(texts).encode(texts), lang)


def test_lexicons_have_same_keys() -> None:
    assert set(lexicon("es")) == set(lexicon("en"))
    assert set(lexicon("es")["reasons"]) == set(lexicon("en")["reasons"])
    merged = lexicon("fr")  # unknown language: union of both
    assert "pues" in merged["fillers"] and "um" in merged["fillers"]


def test_hook_signal() -> None:
    sents = _sentences(
        [
            "¿Sabías que nadie lee las instrucciones?",
            "El noventa por ciento las ignora.",
            "Y luego vemos eso.",
        ]
    )
    sc = _scorer(sents)
    q, reasons = sc.hook(0)
    assert q >= 0.6 and "question_hook" in reasons
    n, reasons = sc.hook(1)
    assert "number_hook" in reasons
    assert sc.hook(2)[0] < 0.3


def test_autonomy_and_closure() -> None:
    sents = _sentences(
        [
            "Como decía antes, esto es así.",
            "La clave es practicar cada día, por eso funciona.",
            "Y lo que pasa es que",
        ]
    )
    sc = _scorer(sents)
    assert sc.autonomy(0) < 0.4
    assert sc.autonomy(1) > 0.8
    assert sc.closure(2) > 0.7  # ends at sentence 1 with a punchline
    assert sc.closure(3) < 0.3  # ends on "que": mid-thought


def test_pace_penalises_fillers_and_slowness() -> None:
    fluent = _sentences(["Esto es una frase con un ritmo bastante natural y claro."])
    slow = _sentences(["Esto es lento."], wps=0.8)
    fillers = _sentences(["Pues eh bueno o sea vale pues eh bueno digamos vale."])
    assert _scorer(fluent).pace(0, 1) == pytest.approx(1.0)
    assert len(slow) == 3  # each word became its own unit (pauses > 0.6 s)
    assert _scorer(slow).pace(0, len(slow)) < 0.7
    assert _scorer(fillers).pace(0, 1) < 0.5


def test_cohesion_pairwise() -> None:
    same = _sentences(
        [
            "Las diapositivas tienen demasiado texto.",
            "Menos texto en las diapositivas.",
            "El texto de las diapositivas distrae.",
        ]
    )
    mixed = _sentences(
        [
            "Las diapositivas tienen demasiado texto.",
            "Mi perro come pienso caro.",
            "Mañana lloverá en Madrid.",
        ]
    )
    assert _scorer(same).cohesion(0, 3) > _scorer(mixed).cohesion(0, 3)
    assert _scorer(mixed).cohesion(0, 3) == pytest.approx(0.0, abs=1e-4)


def test_windows_respect_bounds() -> None:
    sents = _sentences([f"Frase número {i} con varias palabras más." for i in range(30)])
    ws = candidates.windows(sents, 15, 30)
    assert ws
    for i, j in ws:
        dur = sents[j - 1].end - sents[i].start
        assert 15 - candidates.TOLERANCE_S <= dur <= 30 + candidates.TOLERANCE_S


def test_bounds_padding_never_reaches_neighbours() -> None:
    sents = _sentences(["Uno dos tres.", "Cuatro cinco seis.", "Siete ocho nueve."], gap=0.1)
    start, end = bounds(sents, 1, 2, padding=0.15, media_duration=100)
    assert start > sents[0].end and end < sents[2].start
    start, end = bounds(sents, 0, 3, padding=0.15, media_duration=sents[-1].end + 0.05)
    assert start == 0.0 and end == pytest.approx(sents[-1].end + 0.05, abs=1e-3)


def test_mmr_no_overlap_and_diversity() -> None:
    vecs = np.eye(10, dtype=np.float32)
    ws = [Window(0, 3, 90), Window(1, 4, 89), Window(5, 8, 60), Window(6, 9, 59)]
    picked = select_diverse(ws, vecs, k=4, lam=0.75, total_s=100)
    assert [(w.i, w.j) for w in picked] == [(0, 3), (5, 8)]  # overlapping ones excluded


def test_extractive_hook_and_title() -> None:
    sents = _sentences(
        [
            "Bueno, pues el error número uno es hablar rápido y sin pausas, algo que hacemos casi "
            "todos cuando estamos nerviosos delante de mucha gente.",
            "Respira.",
        ]
    )
    h = extract.hook(sents, 0, "es")
    assert h.startswith("El error número uno") and len(h) <= extract.HOOK_MAX and h.endswith("…")
    texts = [s.text for s in sents]
    t = extract.title(sents, 0, 2, TfidfEncoder("es").fit(texts).encode(texts), "es")
    assert t and not t.endswith(".") and len(t) <= extract.TITLE_MAX and t[0].isupper()


def test_select_clips_end_to_end_and_ranked() -> None:
    files = sorted((ROOT / "eval" / "annotations").glob("synthetic_*.json"))
    assert files
    words, moments, lang, length, duration = eval_scoring.load(files[0])
    sents = segment(words, language=lang)
    clips = select_clips(sents, language=lang, length=length, media_duration=duration)
    assert 1 <= len(clips) <= ScoringConfig.load().top_k
    assert [c.rank for c in clips] == list(range(1, len(clips) + 1))
    assert [c.score for c in clips] == sorted((c.score for c in clips), reverse=True)
    spans = sorted((c.start, c.end) for c in clips)
    assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:], strict=False))  # no overlaps
    for c in clips:
        assert 0 <= c.score <= 100 and c.title and c.hook
        assert set(c.reasons) <= set(lexicon(lang)["reasons"])
        assert len(c.reasons) <= 4


def test_eval_recall_on_synthetic_set() -> None:
    """Regression guard for the weights (synthetic data; see weights.toml calibration note)."""
    files = sorted((ROOT / "eval" / "annotations").glob("synthetic_*.json"))
    assert eval_scoring.evaluate(files, k=5, config=ScoringConfig.load(), verbose=False) >= 0.85


def test_very_short_media_gives_one_clip() -> None:
    sents = _sentences(["Hola a todos.", "Esto dura muy poco."])
    clips = select_clips(sents, language="es", length=ClipLength.SHORT, media_duration=10)
    assert len(clips) == 1 and clips[0].sentence_start == 0 and clips[0].sentence_end == 2
