"""Shared fixtures: synthetic media generated with the resolved ffmpeg (no network, no models)."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from clipforge.core.binaries import FfmpegBinaries, resolve_ffmpeg
from clipforge.core.net import uninstall_offline_guard

# Spaces, accents and emoji: the paths real users have.
TRICKY_DIR = "mis vídeos ñ 🎬"


@pytest.fixture(scope="session")
def ff() -> FfmpegBinaries:
    return resolve_ffmpeg()


def _make(ff: FfmpegBinaries, out: Path, args: list[str]) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [str(ff.ffmpeg), "-hide_banner", "-loglevel", "error", "-y", *args, str(out)],
        check=True,
        timeout=120,
    )
    return out


@pytest.fixture(scope="session")
def media_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("media") / TRICKY_DIR


@pytest.fixture(scope="session")
def video_mp4(ff: FfmpegBinaries, media_dir: Path) -> Path:
    """5 s 320x240 @25 fps H.264 + AAC 440 Hz tone."""
    return _make(
        ff,
        media_dir / "clase de prueba 😀.mp4",
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=320x240:r=25:d=5",
            "-f",
            "lavfi",
            "-i",
            "sine=f=440:d=5",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
        ],
    )


@pytest.fixture(scope="session")
def video_two_tracks_rotated(ff: FfmpegBinaries, media_dir: Path, video_mp4: Path) -> Path:
    """Two audio tracks (2nd tagged 'spa') and a 90° display matrix, like a phone recording."""
    base = _make(
        ff,
        media_dir / "_tmp_two.mp4",
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=320x240:r=30:d=3",
            "-f",
            "lavfi",
            "-i",
            "sine=f=300:d=3",
            "-f",
            "lavfi",
            "-i",
            "sine=f=900:d=3",
            "-map",
            "0",
            "-map",
            "1",
            "-map",
            "2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-metadata:s:a:1",
            "language=spa",
        ],
    )
    out = _make(
        ff,
        media_dir / "móvil rotado.mov",
        ["-display_rotation", "90", "-i", str(base), "-map", "0", "-c", "copy"],
    )
    base.unlink()
    return out


@pytest.fixture(scope="session")
def audio_mp3(ff: FfmpegBinaries, media_dir: Path) -> Path:
    return _make(ff, media_dir / "podcast.mp3", ["-f", "lavfi", "-i", "sine=f=220:d=4", "-c:a", "libmp3lame"])


@pytest.fixture(scope="session")
def video_no_audio(ff: FfmpegBinaries, media_dir: Path) -> Path:
    return _make(
        ff,
        media_dir / "mudo.mp4",
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=160x120:r=25:d=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
        ],
    )


@pytest.fixture
def no_offline_guard() -> Iterator[None]:
    yield
    uninstall_offline_guard()
