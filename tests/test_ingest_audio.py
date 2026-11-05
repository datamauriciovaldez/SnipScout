from pathlib import Path

import numpy as np
import pytest

from snipscout.core import audio, ingest
from snipscout.core.binaries import FfmpegBinaries
from snipscout.core.errors import CancelledError, NoSpeechError, UnsupportedMediaError
from snipscout.core.procs import CancelToken


@pytest.fixture(params=["ffprobe", "pyav"])
def prober(request: pytest.FixtureRequest, ff: FfmpegBinaries) -> Path | None:
    if request.param == "ffprobe":
        if ff.ffprobe is None:
            pytest.skip("no ffprobe on this system")
        return ff.ffprobe
    return None


def test_probe_video(video_mp4: Path, prober: Path | None) -> None:
    info = ingest.probe(video_mp4, prober)
    assert info.has_video and info.video_codec == "h264"
    assert (info.width, info.height) == (320, 240)
    assert info.fps == pytest.approx(25, abs=0.01)
    assert info.duration == pytest.approx(5, abs=0.15)
    assert len(info.audio_tracks) == 1 and info.audio_tracks[0].codec == "aac"
    assert info.rotation == 0
    assert info.size_bytes > 0


def test_probe_rotation_and_tracks(video_two_tracks_rotated: Path, prober: Path | None) -> None:
    info = ingest.probe(video_two_tracks_rotated, prober)
    assert info.rotation == 90
    assert info.display_size == (240, 320)
    assert [t.index for t in info.audio_tracks] == [0, 1]
    assert info.audio_tracks[1].language == "spa"


def test_probe_audio_only(audio_mp3: Path, prober: Path | None) -> None:
    info = ingest.probe(audio_mp3, prober)
    assert not info.has_video
    assert info.audio_tracks and info.duration == pytest.approx(4, abs=0.2)


def test_probe_rejects_bad_inputs(tmp_path: Path, prober: Path | None) -> None:
    with pytest.raises(UnsupportedMediaError):
        ingest.probe(tmp_path / "missing.mp4", prober)
    txt = tmp_path / "notes.txt"
    txt.write_text("hello")
    with pytest.raises(UnsupportedMediaError) as exc:
        ingest.probe(txt, prober)
    assert exc.value.code == "unsupported_media"
    fake = tmp_path / "fake.mp4"
    fake.write_bytes(b"this is not a video" * 100)
    with pytest.raises(UnsupportedMediaError):
        ingest.probe(fake, prober)


def test_ffprobe_json_parsing_vfr_and_legacy_rotate(tmp_path: Path) -> None:
    f = tmp_path / "x.mp4"
    f.write_bytes(b"0")
    data = {
        "format": {"format_name": "mov", "duration": "10.0"},
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "2997/100",
                "r_frame_rate": "60/1",
                "tags": {"rotate": "-90"},
            },
            {"codec_type": "video", "codec_name": "mjpeg", "disposition": {"attached_pic": 1}},
            {"codec_type": "audio", "codec_name": "aac", "channels": 2, "sample_rate": "48000"},
        ],
    }
    info = ingest._from_ffprobe_json(f, data)
    assert info.variable_frame_rate
    assert info.rotation == 270
    assert info.video_codec == "h264"


def test_extract_audio(ff: FfmpegBinaries, video_mp4: Path, tmp_path: Path) -> None:
    info = ingest.probe(video_mp4, ff.ffprobe)
    progress: list[float] = []
    out = audio.extract_audio(ff.ffmpeg, info, tmp_path / "a b ñ" / "audio.wav", on_progress=progress.append)
    samples = audio.load_wav(out)
    assert len(samples) / audio.SAMPLE_RATE == pytest.approx(5, abs=0.1)
    assert 0.1 < float(np.abs(samples).max()) <= 1.0
    assert progress and progress[-1] == 1.0
    assert not list(out.parent.glob("*.part.wav"))


def test_extract_audio_track_and_limit(
    ff: FfmpegBinaries, video_two_tracks_rotated: Path, tmp_path: Path
) -> None:
    info = ingest.probe(video_two_tracks_rotated, ff.ffprobe)
    out = audio.extract_audio(ff.ffmpeg, info, tmp_path / "t.wav", track=1, max_seconds=1.5)
    samples = audio.load_wav(out)
    assert len(samples) / audio.SAMPLE_RATE == pytest.approx(1.5, abs=0.05)
    # Track 1 is the 900 Hz tone: count zero crossings over 1 s.
    one_s = samples[: audio.SAMPLE_RATE]
    crossings = int(np.sum(np.diff(np.signbit(one_s)) != 0))
    assert crossings / 2 == pytest.approx(900, rel=0.05)


def test_extract_audio_without_audio_track(ff: FfmpegBinaries, video_no_audio: Path, tmp_path: Path) -> None:
    info = ingest.probe(video_no_audio, ff.ffprobe)
    assert info.audio_tracks == []
    with pytest.raises(NoSpeechError):
        audio.extract_audio(ff.ffmpeg, info, tmp_path / "x.wav")


def test_extract_audio_cancel(ff: FfmpegBinaries, video_mp4: Path, tmp_path: Path) -> None:
    info = ingest.probe(video_mp4, ff.ffprobe)
    token = CancelToken()
    token.cancel()
    with pytest.raises(CancelledError):
        audio.extract_audio(ff.ffmpeg, info, tmp_path / "c.wav", cancel=token)
    assert not (tmp_path / "c.wav").exists()
    assert not (tmp_path / "c.part.wav").exists()


def test_rms_envelope() -> None:
    sr = audio.SAMPLE_RATE
    loud = np.full(sr, 0.5, dtype=np.float32)
    quiet = np.zeros(sr, dtype=np.float32)
    env = audio.rms_envelope(np.concatenate([loud, quiet]), hop_s=0.5)
    assert env.tolist() == pytest.approx([0.5, 0.5, 0.0, 0.0])


def test_envelope_peaks_range_and_stable_scale() -> None:
    env = np.concatenate([np.full(100, 0.1), np.full(100, 0.5), np.full(100, 0.2)]).astype(np.float32)  # 15 s
    whole = audio.envelope_peaks(env, points=3, top=0.5)
    assert whole == pytest.approx([0.2, 1.0, 0.4])
    zoom = audio.envelope_peaks(env, points=10, start=5.0, end=10.0, top=0.5)  # only the loud part
    assert len(zoom) == 10 and zoom == pytest.approx([1.0] * 10)
    assert audio.envelope_peaks(env, points=4, start=14.0, end=99.0, top=0.5) == pytest.approx([0.4] * 4)
    assert audio.envelope_peaks(np.zeros(0, dtype=np.float32), points=5) == []
