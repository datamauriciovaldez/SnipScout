"""Group words into sentence-like units and compute per-sentence features."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from clipforge.core.models import Sentence, Word
from clipforge.core.text import count_phrases, lexicon

PAUSE_SPLIT_S = 0.6
MAX_WORDS = 40
MAX_SECONDS = 20.0
_END_PUNCT = (".", "?", "!", "…", "。", "？", "！")
RMS_HOP_S = 0.05


def _features(
    words: list[Word], i: int, j: int, index: int, rms: npt.NDArray[np.float32] | None, fillers: list[str]
) -> Sentence:
    chunk = words[i:j]
    start, end = chunk[0].start, chunk[-1].end
    text = " ".join(w.text for w in chunk)
    # Fix spacing before punctuation that Whisper emits as separate tokens.
    for p in (" ,", " .", " ?", " !", " …", " :", " ;"):
        text = text.replace(p, p.strip())
    dur = max(end - start, 1e-3)
    rms_mean = rms_var = 0.0
    if rms is not None and len(rms):
        a, b = int(start / RMS_HOP_S), max(int(end / RMS_HOP_S), int(start / RMS_HOP_S) + 1)
        seg = rms[a:b]
        if len(seg):
            rms_mean = float(seg.mean())
            rms_var = float(seg.std() / rms_mean) if rms_mean > 1e-6 else 0.0
    return Sentence(
        index=index,
        start=start,
        end=end,
        text=text,
        word_start=i,
        word_end=j,
        words_per_sec=round(len(chunk) / dur, 3),
        pause_before=round(start - words[i - 1].end, 3) if i > 0 else 0.0,
        pause_after=round(words[j].start - end, 3) if j < len(words) else 0.0,
        confidence=round(float(np.mean([w.prob for w in chunk])), 3),
        rms_mean=round(rms_mean, 5),
        rms_variation=round(rms_var, 4),
        fillers=count_phrases(text, fillers),
    )


def segment(
    words: list[Word], *, language: str | None = None, rms: npt.NDArray[np.float32] | None = None
) -> list[Sentence]:
    """Split on sentence-ending punctuation, on pauses > 0.6 s, or when a unit gets too long.

    ``rms`` is the envelope from ``audio.rms_envelope`` (hop 0.05 s) of the same audio.
    """
    fillers = lexicon(language).get("fillers", [])
    out: list[Sentence] = []
    i = 0
    for k, w in enumerate(words):
        last = k == len(words) - 1
        gap = words[k + 1].start - w.end if not last else 0.0
        n, dur = k - i + 1, w.end - words[i].start
        if last or w.text.endswith(_END_PUNCT) or gap > PAUSE_SPLIT_S or n >= MAX_WORDS or dur >= MAX_SECONDS:
            out.append(_features(words, i, k + 1, len(out), rms, fillers))
            i = k + 1
    return out
