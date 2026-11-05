"""Spike 2: faster-whisper on CPU. Measures RTF, peak RSS and word-timestamp error
against sentence boundaries in sample_truth.json. Usage: s2_whisper.py tiny base"""
import json
import resource
import sys
import time
from pathlib import Path

from faster_whisper import WhisperModel

OUT = Path(__file__).parent / "out"
truth = json.loads((OUT / "sample_truth.json").read_text(encoding="utf-8"))
audio_s = truth[-1]["end"] + 0.7

for size in sys.argv[1:] or ["tiny", "base"]:
    t0 = time.perf_counter()
    model = WhisperModel(size, device="cpu", compute_type="int8")
    load_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    segs, info = model.transcribe(str(OUT / "sample.wav"), language="es", word_timestamps=True, vad_filter=True)
    words = [w for s in segs for w in s.words]
    tr_s = time.perf_counter() - t0
    # Boundary error: each true sentence start/end vs nearest word start/end.
    starts = [w.start for w in words]
    ends = [w.end for w in words]
    err_start = [min(abs(t["start"] - s) for s in starts) for t in truth]
    err_end = [min(abs(t["end"] - e) for e in ends) for t in truth]
    errs = sorted(err_start + err_end)
    rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    res = {
        "model": size, "load_s": round(load_s, 2), "transcribe_s": round(tr_s, 2),
        "rtf": round(tr_s / audio_s, 3), "peak_rss_mb": round(rss_mb),
        "n_words": len(words), "boundary_err_median_s": round(errs[len(errs) // 2], 3),
        "boundary_err_p90_s": round(errs[int(len(errs) * 0.9)], 3),
        "text": " ".join(w.word.strip() for w in words)[:300],
    }
    print(json.dumps(res, ensure_ascii=False))
