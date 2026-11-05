"""Speech-to-text with faster-whisper: chunked, resumable, cancellable, with honest progress/ETA.

Audio is always handed to faster-whisper as a float32 numpy array read from our own WAV
(never a path: PyAV 19 breaks faster-whisper's file decoding — see docs/spike-report.md).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt

from clipforge.config import cache_dir
from clipforge.core.audio import SAMPLE_RATE, read_wav_range, wav_duration
from clipforge.core.errors import ModelDownloadError, NoSpeechError
from clipforge.core.models import JobEvent, Transcript, Word
from clipforge.core.modelstore import get_spec, is_installed, model_dir
from clipforge.core.procs import CancelToken

CHUNK_S = 300.0  # 5 min per chunk keeps memory bounded on multi-hour files
QUICK_ANALYSIS_S = 600.0
STAGE = "transcribe"


class SegmentLike(Protocol):
    start: float
    end: float
    text: str
    words: list[Any] | None


class SpeechModel(Protocol):
    def transcribe(self, audio: npt.NDArray[np.float32], **kwargs: Any) -> tuple[Iterable[Any], Any]: ...


def _pick_device() -> tuple[str, str]:
    """GPU if CTranslate2 sees CUDA, otherwise CPU int8. Never required."""
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "int8_float16"
    except (ImportError, RuntimeError, OSError):
        pass
    return "cpu", "int8"


def load_model(name: str) -> SpeechModel:
    if not is_installed(name):
        raise ModelDownloadError("The speech model is not downloaded yet.", details=name)
    from faster_whisper import WhisperModel

    device, compute = _pick_device()
    try:
        return WhisperModel(str(model_dir(name)), device=device, compute_type=compute)  # type: ignore[no-any-return]
    except (RuntimeError, ValueError):
        if device == "cpu":
            raise
        # GPU present but unusable (driver/cuDNN missing): fall back to CPU.
        return WhisperModel(str(model_dir(name)), device="cpu", compute_type="int8")  # type: ignore[no-any-return]


# --- speed statistics (feeds the ETA shown before and during analysis) -----------------------------


def _speed_file() -> Path:
    return cache_dir() / "speed.json"


def measured_rtf(model: str) -> float | None:
    try:
        data = json.loads(_speed_file().read_text(encoding="utf-8"))
        value = data.get(model)
        return float(value) if value else None
    except (OSError, ValueError, TypeError):
        return None


def record_rtf(model: str, rtf: float) -> None:
    """Exponential moving average of the observed real-time factor per model."""
    if not (0.001 < rtf < 50):
        return
    old = measured_rtf(model)
    new = rtf if old is None else 0.7 * old + 0.3 * rtf
    try:
        path = _speed_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, float] = {}
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
        data[model] = round(new, 4)
        path.write_text(json.dumps(data), encoding="utf-8")
    except (OSError, ValueError):
        pass  # statistics are best-effort


def estimate_seconds(audio_seconds: float, model: str) -> float:
    return audio_seconds * (measured_rtf(model) or get_spec(model).default_rtf)


BENCHMARK_WAV = Path(__file__).resolve().parents[1] / "assets" / "benchmark_es.wav"


def run_benchmark(model: SpeechModel, model_name: str) -> float:
    """Transcribe the bundled ~10 s speech sample and record the real-time factor."""
    from clipforge.core.audio import load_wav

    samples = load_wav(BENCHMARK_WAV)
    t0 = time.perf_counter()
    segments, _ = model.transcribe(samples, language="es", word_timestamps=True, vad_filter=True)
    for _ in segments:  # the generator does the work
        pass
    rtf = (time.perf_counter() - t0) / (len(samples) / SAMPLE_RATE)
    record_rtf(model_name, rtf)
    return rtf


# --- main loop -------------------------------------------------------------------------------------


def transcribe(
    model: SpeechModel,
    model_name: str,
    wav: Path,
    *,
    transcript: Transcript | None = None,
    language: str | None = None,
    quick: bool = False,
    save: Callable[[Transcript], None] | None = None,
    on_event: Callable[[JobEvent], None] | None = None,
    cancel: CancelToken | None = None,
) -> Transcript:
    """Transcribe ``wav`` in chunks, resuming from ``transcript.processed_until`` if given.

    The last segment of each non-final chunk is dropped and re-transcribed in the next chunk,
    because it may have been cut at the chunk boundary.
    """
    total = wav_duration(wav)
    limit = min(total, QUICK_ANALYSIS_S) if quick else total
    if transcript is None or transcript.model != model_name:
        transcript = Transcript(model=model_name, duration=limit, language=language)
    elif (
        transcript.duration != limit
    ):  # e.g. quick analysis first, full analysis now: continue, don't restart
        transcript.complete = False
        transcript.duration = limit
    lang = language or transcript.language
    pos = transcript.processed_until
    started, start_pos = time.perf_counter(), pos

    def emit(processed: float, text: str = "") -> None:
        if not on_event:
            return
        done = processed - start_pos
        elapsed = time.perf_counter() - started
        remaining = limit - processed
        eta = elapsed / done * remaining if done > 5 else estimate_seconds(remaining, model_name)
        on_event(
            JobEvent(
                stage=STAGE,
                progress=min(1.0, processed / limit) if limit else 1.0,
                message="stage.transcribe",
                params={
                    "processed_s": round(processed, 1),
                    "total_s": round(limit, 1),
                    "eta_s": round(eta),
                    "text": text,
                },
            )
        )

    emit(pos)
    while pos < limit - 0.25:
        if cancel:
            cancel.raise_if_cancelled()
        chunk_end = min(pos + CHUNK_S, limit)
        is_last = chunk_end >= limit
        samples = read_wav_range(wav, pos, chunk_end)
        segments, info = model.transcribe(
            samples,
            language=lang,
            word_timestamps=True,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        if lang is None:
            lang = getattr(info, "language", None)
            transcript.language = lang
        collected: list[SegmentLike] = []
        for seg in segments:
            if cancel:
                cancel.raise_if_cancelled()
            collected.append(seg)
            emit(pos + seg.end, seg.text.strip())
        keep = collected if is_last or len(collected) <= 1 else collected[:-1]
        new_pos = chunk_end if is_last or not keep else pos + keep[-1].end
        if new_pos <= pos + 1.0:  # guarantee forward progress
            new_pos, keep = chunk_end, collected
        last_end = transcript.words[-1].end if transcript.words else -1.0
        for seg in keep:
            for w in seg.words or []:
                start, end = pos + float(w.start), pos + float(w.end)
                if start + 1e-3 < last_end or not str(w.word).strip():
                    continue
                transcript.words.append(
                    Word(
                        text=str(w.word).strip(),
                        start=round(start, 3),
                        end=round(end, 3),
                        prob=round(float(w.probability), 3),
                    )
                )
                last_end = end
        transcript.processed_until = round(new_pos, 3)
        pos = new_pos
        if save and not is_last:
            save(transcript)  # chunk boundary = resume point
    transcript.complete = True
    if save:
        save(transcript)
    if pos - start_pos > 30:
        record_rtf(model_name, (time.perf_counter() - started) / (pos - start_pos))
    emit(limit)
    if not transcript.words:
        raise NoSpeechError("No speech was found in this file.")
    return transcript
