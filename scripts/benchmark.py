"""Measure transcription speed and peak memory per speech model on this computer.

Each model runs in a fresh child process, so peak RAM is that model's own. Models that are not
downloaded yet are downloaded first (one-time, from Hugging Face). Prints a Markdown table.
Usage: uv run python scripts/benchmark.py path/to/talk.mp4 [--models tiny base small]
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CHILD = """
import json, sys, time, threading
from pathlib import Path
import psutil
from snipscout.core.transcribe import load_model, transcribe
name, wav = sys.argv[1], Path(sys.argv[2])
proc, peak = psutil.Process(), [0]
def watch():
    while True:
        peak[0] = max(peak[0], proc.memory_info().rss)
        time.sleep(0.05)
threading.Thread(target=watch, daemon=True).start()
t0 = time.perf_counter()
model = load_model(name)
t1 = time.perf_counter()
tr = transcribe(model, name, wav)
t2 = time.perf_counter()
print(json.dumps({"load_s": t1 - t0, "transcribe_s": t2 - t1, "peak_rss": peak[0], "words": len(tr.words)}))
"""


def main() -> int:
    import psutil

    from snipscout.core import audio, ingest, modelstore
    from snipscout.core.binaries import resolve_ffmpeg

    ap = argparse.ArgumentParser()
    ap.add_argument("media", type=Path)
    ap.add_argument("--models", nargs="+", default=["tiny", "base", "small"])
    args = ap.parse_args()

    ff = resolve_ffmpeg()
    info = ingest.probe(args.media, ff.ffprobe)
    wav = Path(tempfile.mkdtemp(prefix="snipscout-bench-")) / "audio.wav"
    audio.extract_audio(ff.ffmpeg, info, wav)
    minutes = audio.wav_duration(wav) / 60
    cpu = platform.processor() or platform.machine()
    ram_gb = psutil.virtual_memory().total / 1024**3
    print(f"{platform.system()} {platform.release()} · {cpu} · {psutil.cpu_count(logical=True)} logical CPUs")
    print(f"{ram_gb:.1f} GB RAM · audio {minutes:.2f} min\n")
    print("| Model | Download | Load | Time per minute of audio | Peak RAM |")
    print("|---|---|---|---|---|")
    for name in args.models:
        if not modelstore.is_installed(name):
            modelstore.download_model(name)
        size = modelstore.get_spec(name).total_bytes
        out = subprocess.run(  # noqa: S603 - fixed interpreter and our own code, no shell
            [sys.executable, "-c", CHILD, name, str(wav)],
            capture_output=True,
            text=True,
            timeout=3600,
            check=True,
        )
        r = json.loads(out.stdout.strip().splitlines()[-1])
        print(
            f"| {name} | {size / 1e6:.0f} MB | {r['load_s']:.1f} s | {r['transcribe_s'] / minutes:.1f} s | "
            f"{r['peak_rss'] / 1024**3:.2f} GB |"
        )
        time.sleep(1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
