"""Audio extraction (mono 16 kHz WAV) and loading for analysis."""

from __future__ import annotations

import wave
from collections.abc import Callable
from pathlib import Path

import numpy as np
import numpy.typing as npt

from clipforge.core.errors import NoSpeechError
from clipforge.core.models import MediaInfo
from clipforge.core.procs import CancelToken, run_ffmpeg

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
