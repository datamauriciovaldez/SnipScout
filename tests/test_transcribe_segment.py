from __future__ import annotations

import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from snipscout.core import transcribe
from snipscout.core.audio import SAMPLE_RATE
from snipscout.core.errors import CancelledError, NoSpeechError
from snipscout.core.models import JobEvent, Transcript, Word
from snipscout.core.procs import CancelToken
from snipscout.core.segment import segment


def _wav(path: Path, seconds: float) -> Path:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(np.zeros(int(seconds * SAMPLE_RATE), dtype="<i2").tobytes())
    return path


@dataclass
class FW:  # faster-whisper Word lookalike
    start: float
    end: float
    word: str
    probability: float = 0.9


@dataclass
class FS:  # faster-whisper Segment lookalike
    start: float
    end: float
    text: str
    words: list[FW] = field(default_factory=list)


@dataclass
class Info:
    language: str = "es"


class FakeModel:
    """Emits one 'w<abs_second>' word per second of audio, grouped in 4 s segments."""

    def __init__(self, offsets: list[float], silent: bool = False) -> None:
        self.calls: list[int] = []
        self.offsets = offsets  # absolute chunk start, appended by the test via call order
        self.silent = silent

    def transcribe(self, audio: np.ndarray, **kw: Any) -> tuple[list[FS], Info]:
        assert audio.dtype == np.float32  # always arrays, never paths
        assert kw["word_timestamps"] and kw["vad_filter"]
        n = len(audio) / SAMPLE_RATE
        self.calls.append(len(audio))
        if self.silent:
            return [], Info()
        segs = []
        t = 0.0
        while t + 1 <= n + 1e-6:
            seg_end = min(t + 4, n)
            words = [FW(s + 0.1, s + 0.8, f"w{round(s)}") for s in np.arange(t, seg_end - 0.5, 1.0)]
            segs.append(FS(t, seg_end, " ".join(w.word for w in words), words))
            t = seg_end
        return segs, Info()


def test_single_chunk(tmp_path: Path) -> None:
    wav = _wav(tmp_path / "a.wav", 10)
    events: list[JobEvent] = []
    saved: list[Transcript] = []
    t = transcribe.transcribe(FakeModel([0]), "base", wav, on_event=events.append, save=saved.append)
    assert t.complete and t.language == "es" and t.processed_until == pytest.approx(10)
    assert [w.text for w in t.words] == [f"w{i}" for i in range(10)]
    assert events[-1].progress == 1.0 and events[-1].params["total_s"] == 10
    assert saved and saved[-1].complete


def test_chunks_offsets_and_boundary_segment_redone(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(transcribe, "CHUNK_S", 10.0)
    wav = _wav(tmp_path / "a.wav", 25)
    saved: list[float] = []
    t = transcribe.transcribe(FakeModel([]), "base", wav, save=lambda tr: saved.append(tr.processed_until))
    assert t.complete
    # Chunk 1 covers 0-10 s, drops its last segment (8-10 s, maybe cut) and resumes at 8 s.
    assert saved[0] == pytest.approx(8.0)
    # Every second of audio yields exactly one word, at the right absolute time, no duplicates.
    assert [int(w.start) for w in t.words] == list(range(25))
    assert all(w.start == pytest.approx(int(w.start) + 0.1) for w in t.words)


def test_resume_from_saved_transcript(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(transcribe, "CHUNK_S", 10.0)
    wav = _wav(tmp_path / "a.wav", 20)
    partial = Transcript(
        model="base",
        duration=20,
        language="es",
        processed_until=8.0,
        words=[Word(text=f"w{i}", start=i + 0.1, end=i + 0.8) for i in range(8)],
    )
    model = FakeModel([8.0])
    t = transcribe.transcribe(model, "base", wav, transcript=partial)
    assert model.calls[0] == int(10 * SAMPLE_RATE)  # started at 8 s, not 0
    assert [int(w.start) for w in t.words] == list(range(20))
    assert t.words[8].start == pytest.approx(8.1)


def test_quick_analysis_limits_audio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transcribe, "QUICK_ANALYSIS_S", 6.0)
    wav = _wav(tmp_path / "a.wav", 30)
    t = transcribe.transcribe(FakeModel([0]), "base", wav, quick=True)
    assert t.duration == 6.0 and t.words[-1].end <= 6.0


def test_cancel(tmp_path: Path) -> None:
    wav = _wav(tmp_path / "a.wav", 10)
    token = CancelToken()

    def on_event(e: JobEvent) -> None:
        if e.progress > 0.3:
            token.cancel()

    with pytest.raises(CancelledError):
        transcribe.transcribe(FakeModel([0]), "base", wav, on_event=on_event, cancel=token)


def test_no_speech(tmp_path: Path) -> None:
    wav = _wav(tmp_path / "a.wav", 5)
    with pytest.raises(NoSpeechError):
        transcribe.transcribe(FakeModel([0], silent=True), "base", wav)


def test_rtf_stats(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SNIPSCOUT_CACHE_DIR", str(tmp_path))
    assert transcribe.estimate_seconds(100, "base") == pytest.approx(18)  # H0 default
    transcribe.record_rtf("base", 0.5)
    assert transcribe.estimate_seconds(100, "base") == pytest.approx(50)
    transcribe.record_rtf("base", 0.1)
    assert transcribe.measured_rtf("base") == pytest.approx(0.38)


# --- segmentation ----------------------------------------------------------------------------------


def _words(spec: list[tuple[str, float, float]]) -> list[Word]:
    return [Word(text=t, start=s, end=e, prob=0.8) for t, s, e in spec]


def test_segment_on_punctuation_and_pause() -> None:
    words = _words(
        [
            ("¿Sabías", 0.0, 0.4),
            ("esto?", 0.5, 0.9),  # ends with ?
            ("Pues", 1.0, 1.2),
            ("mira", 1.3, 1.6),  # long pause after
            ("ahora", 2.5, 2.8),
            ("sí.", 2.9, 3.1),
        ]
    )
    s = segment(words, language="es")
    assert [x.text for x in s] == ["¿Sabías esto?", "Pues mira", "ahora sí."]
    assert s[1].pause_after == pytest.approx(0.9)
    assert s[2].pause_before == pytest.approx(0.9)
    assert s[1].fillers == 1  # "pues"
    assert (s[0].word_start, s[0].word_end) == (0, 2)
    assert s[0].words_per_sec == pytest.approx(2 / 0.9, rel=1e-3)


def test_segment_max_words() -> None:
    words = _words([(f"w{i}", i * 0.3, i * 0.3 + 0.25) for i in range(100)])
    s = segment(words)
    assert all(x.word_end - x.word_start <= 40 for x in s)
    assert s[-1].word_end == 100


def test_segment_rms_features() -> None:
    words = _words([("hola", 0.0, 1.0), ("mundo.", 1.0, 2.0)])
    env = np.array([0.1] * 20 + [0.3] * 20, dtype=np.float32)  # 0.05 s hop
    s = segment(words, rms=env)[0]
    assert s.rms_mean == pytest.approx(0.2, abs=1e-4)
    assert s.rms_variation == pytest.approx(0.5, abs=1e-3)


def test_segment_empty() -> None:
    assert segment([]) == []


@pytest.mark.slow
def test_real_whisper_tiny_on_benchmark_sample(tmp_path: Path) -> None:
    """Downloads the real tiny model (~78 MB) and transcribes the bundled Spanish sample."""
    from snipscout.core import modelstore

    modelstore.download_model("tiny")
    model = transcribe.load_model("tiny")
    t = transcribe.transcribe(model, "tiny", transcribe.BENCHMARK_WAV, language="es")
    text = " ".join(w.text for w in t.words).lower()
    assert "por ciento" in text and "enseñar" in text  # tiny garbles the robotic voice elsewhere
    assert t.words[0].start == pytest.approx(0.5, abs=0.4)
    sentences = segment(t.words, language="es")
    assert len(sentences) >= 2
    assert transcribe.run_benchmark(model, "tiny") < 2.0
