"""Measure how many annotated "favourite moments" appear in SnipScout's top-K proposals.

Annotation format (eval/annotations/*.json):
  {
    "name": "...", "language": "es", "length": "short",
    # either a real transcript produced by SnipScout ...
    "transcript": "path/to/transcript.json",          # relative to the annotation file
    "moments": [[start_s, end_s], ...],
    # ... or synthetic sentences (words are timed at a constant speaking rate)
    "sentences": [{"text": "...", "pause_after": 0.7}, ...],
    "moments_sentences": [[first_idx, end_idx_exclusive], ...]
  }

A moment counts as found when some top-K clip covers at least 50% of it. The script also prints what a random
choice of K non-overlapping candidate windows scores on the same files: any tuning must beat that clearly.

Usage: uv run python scripts/eval_scoring.py [--k 5] [--weights file.toml] [files...]
       (default: every annotation under eval/annotations, synthetic and real)
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from snipscout.core import candidates
from snipscout.core.models import ClipLength, Transcript, Word
from snipscout.core.scoring import ScoringConfig
from snipscout.core.segment import segment
from snipscout.core.select import select_clips

ROOT = Path(__file__).resolve().parents[1]
WPS = 2.6


def synth_words(sentences: list[dict[str, object]]) -> tuple[list[Word], list[tuple[float, float]]]:
    words: list[Word] = []
    spans = []
    t = 0.5
    for s in sentences:
        toks = str(s["text"]).split()
        start = t
        for tok in toks:
            words.append(Word(text=tok, start=round(t, 3), end=round(t + 0.8 / WPS * 1.0, 3), prob=0.9))
            t += 1 / WPS
        spans.append((start, words[-1].end))
        t = words[-1].end + float(s.get("pause_after", 0.5))  # type: ignore[arg-type]
    return words, spans


def load(path: Path) -> tuple[list[Word], list[tuple[float, float]], str | None, ClipLength, float]:
    data = json.loads(path.read_text(encoding="utf-8"))
    lang = data.get("language")
    length = ClipLength(data.get("length", "short"))
    if "transcript" in data:
        tr = Transcript.model_validate_json((path.parent / data["transcript"]).read_text(encoding="utf-8"))
        moments = [(float(a), float(b)) for a, b in data["moments"]]
        return tr.words, moments, lang or tr.language, length, tr.duration or tr.words[-1].end
    words, spans = synth_words(data["sentences"])
    moments = [(spans[a][0], spans[b - 1][1]) for a, b in data["moments_sentences"]]
    return words, moments, lang, length, words[-1].end + 1


def coverage(moment: tuple[float, float], clip: tuple[float, float]) -> float:
    inter = max(0.0, min(moment[1], clip[1]) - max(moment[0], clip[0]))
    return inter / max(moment[1] - moment[0], 1e-6)


def evaluate(files: list[Path], k: int, config: ScoringConfig, verbose: bool = True) -> float:
    found_total = moments_total = 0
    for f in files:
        words, moments, lang, length, duration = load(f)
        sentences = segment(words, language=lang)
        clips = select_clips(sentences, language=lang, length=length, media_duration=duration, config=config)
        top = clips[:k]
        found = sum(any(coverage(m, (c.start, c.end)) >= 0.5 for c in top) for m in moments)
        found_total += found
        moments_total += len(moments)
        if verbose:
            print(f"\n{f.name}: {found}/{len(moments)} moments in top-{k}")
            for c in top:
                hit = any(coverage(m, (c.start, c.end)) >= 0.5 for m in moments)
                print(
                    f"  #{c.rank:<2} {c.score:5.1f} {'HIT ' if hit else '    '}{c.start:6.1f}-{c.end:6.1f}s "
                    f"{c.title[:50]!r} {c.reasons}"
                )
    recall = found_total / max(moments_total, 1)
    print(f"\nTOTAL recall@{k}: {found_total}/{moments_total} = {recall:.0%}")
    return recall


def random_baseline(files: list[Path], k: int, runs: int = 2000, seed: int = 0) -> float:
    """Mean recall@k of picking k random non-overlapping candidate windows (same lengths as SnipScout's)."""
    rng = random.Random(seed)  # noqa: S311 - statistics, not security
    data = []
    for f in files:
        words, moments, lang, length, _ = load(f)
        sents = segment(words, language=lang)
        lo, hi = length.bounds
        wins = [(sents[i].start, sents[j - 1].end) for i, j in candidates.windows(sents, lo, hi)]
        data.append((wins, moments))
    total = 0.0
    for _ in range(runs):
        found = n = 0
        for wins, moments in data:
            pick: list[tuple[float, float]] = []
            for w in rng.sample(wins, len(wins)):
                if all(w[1] <= p[0] or w[0] >= p[1] for p in pick):
                    pick.append(w)
                if len(pick) == k:
                    break
            found += sum(any(coverage(m, p) >= 0.5 for p in pick) for m in moments)
            n += len(moments)
        total += found / max(n, 1)
    return total / runs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", type=Path)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--weights", type=Path)
    args = ap.parse_args()
    files = args.files or sorted(
        f for f in (ROOT / "eval" / "annotations").rglob("*.json") if not f.name.endswith(".transcript.json")
    )
    if not files:
        print("No annotation files found.", file=sys.stderr)
        return 1
    evaluate(files, args.k, ScoringConfig.load(args.weights))
    print(f"Random choice of {args.k} windows: {random_baseline(files, args.k):.0%} (mean of 2000 draws)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
