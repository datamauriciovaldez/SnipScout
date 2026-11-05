from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from clipforge.core import ingest, render
from clipforge.core.binaries import FfmpegBinaries
from clipforge.core.errors import CancelledError
from clipforge.core.models import (
    AspectRatio,
    Clip,
    ClipSet,
    JobEvent,
    JobState,
    MediaInfo,
    ProjectSettings,
    ProjectStatus,
    Transcript,
    Word,
)
from clipforge.core.pipeline import Pipeline
from clipforge.core.procs import CancelToken
from clipforge.core.reframe import ReframeMode, default_mode, output_size, video_filter
from clipforge.core.storage import ProjectStore
from clipforge.core.subtitles import (
    PRESETS,
    _ass_color,
    build_ass,
    build_srt,
    build_vtt,
    clip_words,
    escape_ass,
    group_words,
)

sys.path.insert(0, str(Path(__file__).parent))
from test_transcribe_segment import FakeModel  # noqa: E402

SENTENCES = [
    "¿Sabías que el ochenta por ciento de los vídeos se ven sin sonido?",
    "Por eso los subtítulos no son un extra, son obligatorios.",
    "El primer truco es empezar siempre con una pregunta.",
    "La gente decide en dos segundos si se queda o se va.",
    "Y esa es la regla más importante de todas.",
]


def _words(start: float = 0.5, wps: float = 2.5) -> list[Word]:
    words, t = [], start
    for s in SENTENCES:
        for tok in s.split():
            words.append(Word(text=tok, start=round(t, 3), end=round(t + 0.32, 3), prob=0.9))
            t += 1 / wps
        t += 0.7
    return words


# --- subtitles -------------------------------------------------------------------------------------


def test_ass_color_and_escape() -> None:
    assert _ass_color("#8B5CF6") == "&H00F65C8B"
    assert _ass_color("#000000", 0x60) == "&H60000000"
    assert escape_ass("a{\\b}c\nd") == "a｛＼b｝c d"


def test_grouping_3_to_5_words() -> None:
    groups = group_words(_words())
    assert all(1 <= len(g) <= 5 for g in groups)
    assert sum(len(g) for g in groups) == len(_words())
    # Sentence ends always close a line.
    assert all(not any(w.text.endswith((".", "?")) for w in g[:-1]) for g in groups)


def test_no_orphan_word_lines() -> None:
    ws = [
        Word(text=t, start=i * 0.4, end=i * 0.4 + 0.3)
        for i, t in enumerate(["número", "uno", "al", "hablar", "en", "público?"])
    ]
    groups = group_words(ws)
    assert [len(g) for g in groups] != [5, 1]
    assert all(len(g) >= 2 for g in groups)


def test_ass_one_event_per_word_with_highlight() -> None:
    words = _words()
    ass = build_ass(words, "bold-pop", 1080, 1920, vertical=True)
    events = [line for line in ass.splitlines() if line.startswith("Dialogue:")]
    assert len(events) == len(words)
    assert "PlayResX: 1080" in ass and "Inter Black" in ass
    assert all("\\fscx112" in e for e in events)  # active word pops
    assert "¿SABÍAS" in ass  # uppercase preset keeps accents

    # Events never overlap in time.
    def t(s: str) -> float:
        h, m, sec = s.split(":")
        return int(h) * 3600 + int(m) * 60 + float(sec)

    spans = [(t(e.split(",")[1]), t(e.split(",")[2])) for e in events]
    assert all(a[1] <= b[0] + 1e-6 for a, b in zip(spans, spans[1:], strict=False))


def test_karaoke_lights_previous_words() -> None:
    ass = build_ass(_words()[:4], "karaoke", 1080, 1920, vertical=True)
    last = [line for line in ass.splitlines() if line.startswith("Dialogue:")][2]
    assert last.count("\\c&H00FF9F4D") == 3  # words 0..2 lit


@pytest.mark.parametrize("name", list(PRESETS))
def test_every_preset_builds(name: str) -> None:
    assert "Dialogue:" in build_ass(_words()[:6], name, 1920, 1080, vertical=False)


def test_clip_words_relative_times_and_overrides() -> None:
    words = _words()
    clip = Clip(
        id="c01",
        rank=1,
        start=words[3].start - 0.1,
        end=words[9].end + 0.1,
        sentence_start=0,
        sentence_end=2,
        score=50,
        text_overrides={4: "VÍDEOS", 5: ""},
    )
    cw = clip_words(words, clip)
    assert cw[0].text == words[3].text and cw[0].start == pytest.approx(0.1, abs=1e-3)
    assert cw[1].text == "VÍDEOS"
    assert words[5].text not in [w.text for w in cw]  # deleted word
    assert cw[-1].end <= clip.end - clip.start + 1e-6


def test_srt_and_vtt() -> None:
    srt = build_srt(_words()[:6])
    assert srt.startswith("1\n00:00:00,500 --> ")
    vtt = build_vtt(_words()[:6])
    assert vtt.startswith("WEBVTT\n\n00:00:00.500 --> ") and "<00:00:00.900>" in vtt


# --- reframe ---------------------------------------------------------------------------------------


def _media(w: int, h: int, rotation: int = 0) -> MediaInfo:
    return MediaInfo(
        path=Path("x.mp4"),
        size_bytes=1,
        container="mp4",
        duration=10,
        has_video=True,
        width=w,
        height=h,
        rotation=rotation,
    )


def test_output_sizes_and_default_modes() -> None:
    wide = _media(1920, 1080)
    assert output_size(wide, AspectRatio.VERTICAL) == (1080, 1920)
    assert default_mode(wide, AspectRatio.VERTICAL) == ReframeMode.BLUR_PAD
    assert default_mode(wide, AspectRatio.HORIZONTAL) == ReframeMode.CENTER
    assert default_mode(_media(1080, 1920), AspectRatio.VERTICAL) == ReframeMode.CENTER
    phone = _media(3840, 2160, rotation=90)  # 4K portrait phone video
    assert output_size(phone, AspectRatio.ORIGINAL) == (1080, 1920)
    assert default_mode(phone, AspectRatio.VERTICAL) == ReframeMode.CENTER


@pytest.mark.parametrize("mode", list(ReframeMode))
def test_filters_run_in_ffmpeg(ff: FfmpegBinaries, mode: ReframeMode) -> None:
    graph = video_filter(108, 192, mode)
    r = subprocess.run(
        [
            str(ff.ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=320x180:d=0.2",
            "-filter_complex",
            graph,
            "-map",
            "[base]",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stderr


# --- integration without models ---------------------------------------------------------------------


@pytest.fixture(scope="module")
def talk_video(ff: FfmpegBinaries, media_dir: Path) -> Path:
    """24 s 640x360 test pattern with a tone; transcript is synthetic (no speech model needed)."""
    out = media_dir / "charla larga ñ.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            str(ff.ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=640x360:r=25:d=24",
            "-f",
            "lavfi",
            "-i",
            "sine=f=330:d=24",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(out),
        ],
        check=True,
        timeout=120,
    )
    return out


def _project(store: ProjectStore, ff: FfmpegBinaries, video: Path, **settings: Any) -> str:
    media = ingest.probe(video, ff.ffprobe)
    p = store.create(media, ProjectSettings(**settings))
    store.save_transcript(
        p.id,
        Transcript(
            language="es",
            model="base",
            duration=media.duration,
            processed_until=media.duration,
            complete=True,
            words=_words(),
        ),
    )
    return p.id


def _frame(ff: FfmpegBinaries, video: Path, at: float, out: Path) -> np.ndarray:
    subprocess.run(
        [
            str(ff.ffmpeg),
            "-loglevel",
            "error",
            "-y",
            "-ss",
            str(at),
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            str(out),
        ],
        check=True,
        timeout=60,
    )
    return np.frombuffer(out.read_bytes(), dtype=np.uint8)


def test_render_export_end_to_end(ff: FfmpegBinaries, talk_video: Path, tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects")
    pid = _project(store, ff, talk_video, aspect=AspectRatio.VERTICAL, subtitle_style="bold-pop")
    pipe = Pipeline(store, ff)
    # No speech model here: clips are selected from the synthetic transcript directly.
    from clipforge.core.models import ClipLength
    from clipforge.core.select import select_clips

    project = store.load(pid)
    sentences = pipe.sentences(project)
    found = select_clips(sentences, language="es", length=ClipLength.SHORT, media_duration=24, top_k=2)
    assert found
    store.save_clips(pid, ClipSet(clips=found))
    events: list[JobEvent] = []
    out_dir = tmp_path / "salida con espacios ñ"
    result = pipe.render(pid, out_dir=out_dir, on_event=events.append)

    assert store.load(pid).status == ProjectStatus.DONE
    assert events[-1].state == JobState.DONE
    assert len(result.clips) == len(found)
    first = result.clips[0].video
    assert first.name.startswith("clip_01_") and first.suffix == ".mp4"
    probe = (
        json.loads(
            subprocess.run(
                [
                    str(ff.ffprobe or ff.ffmpeg),
                    "-v",
                    "error",
                    "-print_format",
                    "json",
                    "-show_streams",
                    "-show_format",
                    str(first),
                ],
                capture_output=True,
                text=True,
                timeout=60,
            ).stdout
        )
        if ff.ffprobe
        else None
    )
    if probe:
        v = next(s for s in probe["streams"] if s["codec_type"] == "video")
        a = next(s for s in probe["streams"] if s["codec_type"] == "audio")
        assert (v["codec_name"], v["width"], v["height"], v["pix_fmt"]) == ("h264", 1080, 1920, "yuv420p")
        assert a["codec_name"] == "aac"
        dur = float(probe["format"]["duration"])
        assert dur == pytest.approx(found[0].end - found[0].start, abs=0.15)
    # faststart: the moov atom comes before mdat.
    head = first.read_bytes()[:200_000]
    assert head.find(b"moov") != -1 and (head.find(b"mdat") == -1 or head.find(b"moov") < head.find(b"mdat"))
    # Subtitles are burned in: compare the same frame rendered without subtitles.
    meta = json.loads((out_dir / "metadata.json").read_text(encoding="utf-8"))
    assert meta["clips"][0]["reasons"] and meta["clips"][0]["reasons"][0]["text"]
    assert (out_dir / "captions.txt").read_text(encoding="utf-8").startswith("=== clip_01_")
    assert result.clips[0].srt.exists() and result.clips[0].vtt.exists()
    assert not (out_dir / ".clipforge-work").exists()
    if sys.platform != "win32":
        assert first.stat().st_mode & 0o044 == 0o044 and (out_dir / "metadata.json").stat().st_mode & 0o044
    opts = pipe.render_options(store.load(pid))
    opts.burn_subtitles = False
    plain = render.render_clip(
        ff.ffmpeg,
        store.load(pid).source,
        found[0].start,
        found[0].end,
        tmp_path / "w",
        tmp_path / "plain.mp4",
        None,
        opts,
    )
    at = 1.0
    with_subs = _frame(ff, first, at, tmp_path / "a.gray")
    without = _frame(ff, plain, at, tmp_path / "b.gray")
    lower = slice(len(with_subs) // 2, len(with_subs))  # subtitles live in the lower half
    assert np.abs(with_subs[lower].astype(int) - without[lower].astype(int)).mean() > 2.0


def test_hardware_encoder_falls_back(
    ff: FfmpegBinaries, talk_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(render, "available_hw_encoders", lambda _: ["h264_definitely_missing"])
    media = ingest.probe(talk_video, ff.ffprobe)
    opts = render.RenderOptions(width=320, height=568, mode=ReframeMode.CENTER, hardware=True)
    out = render.render_clip(ff.ffmpeg, media, 1, 3, tmp_path / "w", tmp_path / "hw.mp4", None, opts)
    assert out.exists() and out.stat().st_size > 1000
    assert not (tmp_path / "hw.part.mp4").exists()


def test_audio_only_source_renders(ff: FfmpegBinaries, audio_mp3: Path, tmp_path: Path) -> None:
    media = ingest.probe(audio_mp3, ff.ffprobe)
    opts = render.RenderOptions(width=360, height=640, mode=ReframeMode.CENTER)
    out = render.render_clip(ff.ffmpeg, media, 0, 2, tmp_path / "w", tmp_path / "a.mp4", None, opts)
    assert out.exists() and out.stat().st_size > 1000


def test_full_pipeline_offline_with_fake_model(
    ff: FfmpegBinaries,
    talk_video: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    no_offline_guard: None,
) -> None:
    """Autonomy proof: analyze + render with all non-loopback sockets blocked and no API variables."""
    from clipforge.core import net

    for var in ("OPENAI_API_KEY", "GEMINI_API_KEY", "HF_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CLIPFORGE_OFFLINE", "1")
    assert net.enforce_offline_if_requested()
    store = ProjectStore(tmp_path / "projects")
    media = ingest.probe(talk_video, ff.ffprobe)
    pid = store.create(media, ProjectSettings(aspect=AspectRatio.SQUARE, subtitle_style="classic")).id
    events: list[JobEvent] = []
    pipe = Pipeline(store, ff, model_loader=lambda name: FakeModel([]))  # type: ignore[arg-type,return-value]
    clips = pipe.analyze(pid, on_event=events.append)
    assert clips.clips and store.load(pid).status == ProjectStatus.ANALYZED
    stages = [e.stage for e in events]
    assert stages.index("prepare_audio") < stages.index("transcribe") < stages.index("find_moments")
    overall = [e.params["overall"] for e in events if "overall" in e.params]
    assert overall == sorted(overall) and overall[-1] == 1.0
    for c in clips.clips[1:]:
        c.included = False
    store.save_clips(pid, clips)
    result = pipe.render(pid)
    assert len(result.clips) == 1 and result.clips[0].video.exists()


def test_cancel_marks_project(ff: FfmpegBinaries, talk_video: Path, tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects")
    pid = store.create(ingest.probe(talk_video, ff.ffprobe)).id
    token = CancelToken()
    events: list[JobEvent] = []

    def on_event(e: JobEvent) -> None:
        events.append(e)
        if e.stage == "transcribe":
            token.cancel()

    pipe = Pipeline(store, ff, model_loader=lambda name: FakeModel([]))  # type: ignore[arg-type,return-value]
    with pytest.raises(CancelledError):
        pipe.analyze(pid, on_event=on_event, cancel=token)
    assert store.load(pid).status == ProjectStatus.CANCELLED
    assert events[-1].state == JobState.CANCELLED


@pytest.mark.slow
def test_cli_run_real_model_offline(
    ff: FfmpegBinaries,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    no_offline_guard: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Real speech model (must already be downloaded: run the other slow test first) + CLI, fully offline."""
    from clipforge import cli
    from clipforge.core import modelstore
    from clipforge.core.transcribe import BENCHMARK_WAV

    modelstore.download_model("tiny")  # no-op when installed; needs network only the first time
    video = tmp_path / "voz real.mp4"
    subprocess.run(
        [
            str(ff.ffmpeg),
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=640x360:d=10.5",
            "-i",
            str(BENCHMARK_WAV),
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(video),
        ],
        check=True,
        timeout=120,
    )
    real_models = modelstore.models_dir()  # keep using the already-downloaded model
    monkeypatch.setenv("CLIPFORGE_OFFLINE", "1")
    monkeypatch.setenv("CLIPFORGE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(modelstore, "models_dir", lambda: real_models)
    out = tmp_path / "out"
    code = cli.main(["run", str(video), "--model", "tiny", "--lang", "es", "--count", "1", "--out", str(out)])
    assert code == 0, capsys.readouterr().err
    assert list(out.glob("clip_01_*.mp4"))
