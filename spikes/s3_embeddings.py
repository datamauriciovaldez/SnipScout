"""Spike 3: fastembed multilingual MiniLM — download size, load time, throughput,
and whether it separates on-topic from off-topic sentences (es/en)."""
import resource
import sys
import time
from pathlib import Path

import numpy as np
from fastembed import TextEmbedding

name = sys.argv[1] if len(sys.argv) > 1 else "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
cache = Path(__file__).parent / "out" / "fe_cache"
t0 = time.perf_counter()
m = TextEmbedding(name, cache_dir=str(cache))
print(f"model={name} load+download_s={time.perf_counter() - t0:.1f}")
size = sum(p.stat().st_size for p in cache.rglob("*") if p.is_file())
print(f"on_disk_mb={size / 1e6:.0f}")

base = ["Las pausas hacen que el público preste atención.", "Speaking too fast is the number one mistake.",
        "Una historia personal se recuerda durante años.", "Menos texto en las diapositivas, más impacto.",
        "Hoy hace mucho calor en la sala.", "The coffee machine is broken again."]
sents = [base[i % len(base)] + f" ({i})" for i in range(1000)]
t0 = time.perf_counter()
_ = list(m.embed(sents, batch_size=64))
print(f"1000_sentences_s={time.perf_counter() - t0:.2f} peak_rss_mb={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024:.0f}")

e = np.array(list(m.embed(base)))
e /= np.linalg.norm(e, axis=1, keepdims=True)
s = e @ e.T
on = [s[i, j] for i in range(4) for j in range(4) if i < j]
off = [s[i, j] for i in range(4) for j in (4, 5)]
print(f"cos on-topic(public speaking, es+en) mean={np.mean(on):.2f}  vs off-topic mean={np.mean(off):.2f}")
