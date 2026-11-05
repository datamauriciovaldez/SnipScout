import shutil
import stat
import sys
from pathlib import Path

import pytest

from clipforge.core import binaries
from clipforge.core.errors import FfmpegMissingError

FILTERS_OK = """Filters:
  T.. = Timeline support
 ... aresample         A->A       Resample audio data.
 ... ass               V->V       Render ASS subtitles onto input video using the libass library.
"""
ENCODERS_OK = """Encoders:
 V....D libx264              libx264 H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10 (codec h264)
 A....D aac                  AAC (Advanced Audio Coding)
"""


def test_parse_filters_and_encoders() -> None:
    assert binaries._has_token(FILTERS_OK, "ass")
    assert not binaries._has_token(FILTERS_OK, "subtitles")
    assert binaries._has_token(ENCODERS_OK, "libx264")
    # "ass" must match the filter name column, not substrings like "aresample" or "pass".
    assert not binaries._has_token(" ... aresample  A->A  x\n ... pass  x", "ass")


def _fake_exe(tmp_path: Path, name: str) -> Path:
    """A non-working 'ffmpeg' used to test resolution order without running real binaries."""
    p = tmp_path / name
    p.write_text("not a real binary")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return p


def test_candidates_order(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env_exe = _fake_exe(tmp_path, "custom-ffmpeg")
    monkeypatch.setenv("CLIPFORGE_FFMPEG", str(env_exe))
    monkeypatch.setattr(
        binaries.shutil, "which", lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None
    )
    monkeypatch.setattr(binaries, "_imageio_exe", lambda: Path("/pkg/ffmpeg-imageio"))
    sources = [c[0] for c in binaries.candidates()]
    assert sources == ["env", "system", "imageio"]


def test_resolve_skips_unusable_and_reports_all(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    bad = _fake_exe(tmp_path, "bad-ffmpeg")
    monkeypatch.setattr(binaries, "candidates", lambda: [("env", bad)])
    with pytest.raises(FfmpegMissingError) as exc:
        binaries.resolve_ffmpeg(use_cache=False)
    assert exc.value.code == "ffmpeg_missing"
    assert "bad-ffmpeg" in (exc.value.details or "")


def test_resolve_falls_back_to_next_candidate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    bad = _fake_exe(tmp_path, "bad-ffmpeg")
    real = binaries._imageio_exe()
    assert real is not None, "imageio-ffmpeg is a hard dependency"
    monkeypatch.setattr(binaries, "candidates", lambda: [("system", bad), ("imageio", real)])
    found = binaries.resolve_ffmpeg(use_cache=False)
    assert found.source == "imageio"
    assert found.caps.usable


def test_real_ffmpeg_capabilities_and_render() -> None:
    """Real check: the resolved ffmpeg has libass + libx264 and burns an ASS file."""
    found = binaries.resolve_ffmpeg(use_cache=False)
    assert found.caps.has_ass and found.caps.has_libx264 and found.caps.render_ok, found.caps


def test_probe_cache_roundtrip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CLIPFORGE_CACHE_DIR", str(tmp_path / "cache"))
    exe = binaries._imageio_exe()
    assert exe is not None
    first = binaries.probe_capabilities(exe, use_cache=True)
    calls: list[Path] = []
    monkeypatch.setattr(binaries, "_probe_uncached", lambda e: calls.append(e))
    second = binaries.probe_capabilities(exe, use_cache=True)
    assert second == first
    assert calls == []  # served from cache


def test_find_ffprobe_prefers_sibling(tmp_path: Path) -> None:
    ffmpeg = _fake_exe(tmp_path, "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    sibling = _fake_exe(tmp_path, "ffprobe.exe" if sys.platform == "win32" else "ffprobe")
    assert binaries.find_ffprobe(ffmpeg) == sibling


def test_find_ffprobe_none_for_imageio_without_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ffmpeg = _fake_exe(tmp_path, "ffmpeg-linux-x86_64-v9")
    monkeypatch.setattr(binaries.shutil, "which", lambda name: None)
    assert binaries.find_ffprobe(ffmpeg) is None


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="no system ffmpeg")
def test_system_ffmpeg_preferred_when_usable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLIPFORGE_FFMPEG", raising=False)
    found = binaries.resolve_ffmpeg(use_cache=False)
    assert found.source in {"system", "imageio"}  # system first if it has libass + libx264
