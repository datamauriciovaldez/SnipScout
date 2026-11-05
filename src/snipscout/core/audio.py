"""Audio extraction (mono 16 kHz WAV) and loading for analysis."""

from __future__ import annotations

import wave
from collections.abc import Callable
from pathlib import Path

import numpy as np
import numpy.typing as npt

from snipscout.core.errors import NoSpeechError
from snipscout.core.models import MediaInfo
from snipscout.core.procs import CancelToken, run_ffmpeg

SAMPLE_RATE = 16000


def extract_audio(
    ffmpeg: Path,
    media: MediaInfo,
    out_wav: Path,
    *,
    track: int = 0,
    max_seconds: float | None = None,
    on_progress: Callable[[float], None] | None = None,
    cancel: CancelToken | None = None,
) -> Path:
    """Write ``out_wav`` (PCM s16le, mono, 16 kHz) from audio track ``track``.

    Writes to a temp name first so an interrupted extraction is never mistaken for a finished one.
    """
    if not media.audio_tracks:
        raise NoSpeechError("This file has no audio track.", details=str(media.path))
    if not 0 <= track < len(media.audio_tracks):
        track = 0
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_wav.with_name(out_wav.stem + ".part.wav")
    args = ["-i", str(media.path), "-map", f"0:a:{track}", "-vn", "-sn", "-dn"]
    duration = media.duration
    if max_seconds is not None and max_seconds < duration:
        args += ["-t", f"{max_seconds:.3f}"]
        duration = max_seconds
    args += ["-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le", "-f", "wav", str(tmp)]
    try:
        run_ffmpeg(ffmpeg, args, duration=duration, on_progress=on_progress, cancel=cancel)
        tmp.replace(out_wav)
    finally:
        tmp.unlink(missing_ok=True)
    return out_wav


def load_wav(path: Path) -> npt.NDArray[np.float32]:
    """Mono 16 kHz s16 WAV → float32 in [-1, 1] (the format faster-whisper expects)."""
    with wave.open(str(path), "rb") as w:
        if w.getnchannels() != 1 or w.getframerate() != SAMPLE_RATE or w.getsampwidth() != 2:
            raise ValueError(f"expected mono 16 kHz s16 WAV, got {w.getparams()}")
        raw = w.readframes(w.getnframes())
    return (np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0).astype(np.float32)


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def read_wav_range(path: Path, start_s: float, end_s: float) -> npt.NDArray[np.float32]:
    """Read only [start_s, end_s) of a mono 16 kHz s16 WAV (bounded memory for long files)."""
    with wave.open(str(path), "rb") as w:
        if w.getnchannels() != 1 or w.getframerate() != SAMPLE_RATE or w.getsampwidth() != 2:
            raise ValueError(f"expected mono 16 kHz s16 WAV, got {w.getparams()}")
        first = max(0, int(start_s * SAMPLE_RATE))
        last = min(w.getnframes(), int(end_s * SAMPLE_RATE))
        if last <= first:
            return np.zeros(0, dtype=np.float32)
        w.setpos(first)
        raw = w.readframes(last - first)
    return (np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0).astype(np.float32)


def rms_envelope(samples: npt.NDArray[np.float32], hop_s: float = 0.05) -> npt.NDArray[np.float32]:
    """RMS energy per ``hop_s`` window (used for vocal-energy scoring and the waveform)."""
    hop = max(1, int(SAMPLE_RATE * hop_s))
    n = len(samples) // hop
    if n == 0:
        return np.zeros(0, dtype=np.float32)
    frames = samples[: n * hop].reshape(n, hop).astype(np.float64)
    return np.sqrt((frames**2).mean(axis=1)).astype(np.float32)


def rms_envelope_file(path: Path, hop_s: float = 0.05, block_s: float = 300.0) -> npt.NDArray[np.float32]:
    """RMS envelope of a WAV file, read in blocks (bounded memory for multi-hour audio)."""
    total = wav_duration(path)
    parts = []
    pos = 0.0
    while pos < total:
        end = min(total, pos + block_s)
        parts.append(rms_envelope(read_wav_range(path, pos, end), hop_s))
        pos = end
    return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)


def envelope_peaks(
    env: npt.NDArray[np.float32],
    *,
    points: int,
    start: float = 0.0,
    end: float | None = None,
    hop_s: float = 0.05,
    top: float | None = None,
) -> list[float]:
    """Max-of-bucket peaks of an RMS envelope for [start, end), normalised to 0..1.

    ``top`` is the normalisation level; pass one computed on the whole file so bar heights stay
    the same at every zoom level (default: 99th percentile of the whole envelope)."""
    if len(env) == 0 or points <= 0:
        return []
    level = top if top is not None else float(np.percentile(env, 99)) or 1.0
    a = max(0, int(start / hop_s))
    b = len(env) if end is None else min(len(env), max(a + 1, int(np.ceil(end / hop_s))))
    window = env[a:b]
    if len(window) == 0:
        return []
    n = min(points, len(window))
    edges = np.linspace(0, len(window), n + 1).astype(int)
    return [
        round(min(1.0, float(np.max(window[edges[i] : max(edges[i] + 1, edges[i + 1])])) / level), 3)
        for i in range(n)
    ]
