"""Locate a usable ffmpeg (with libass + libx264) and, if available, ffprobe.

Resolution order (see docs/spike-report.md):
1. ``SNIPSCOUT_FFMPEG`` environment variable (explicit override),
2. ``ffmpeg`` on PATH (system build),
3. the binary shipped by the ``imageio-ffmpeg`` wheel (has libass + libx264 on Windows/macOS/Linux).

A candidate counts as usable only after a *real* render: a tiny clip encoded with libx264
while burning an ASS subtitle file through the ``ass`` filter. Results are cached per binary
(path + size + mtime) so the check runs once.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from snipscout.config import cache_dir
from snipscout.core.errors import FfmpegMissingError

PROBE_TIMEOUT_S = 60
_CACHE_VERSION = 1

_PROBE_ASS = """[Script Info]
ScriptType: v4.00+
PlayResX: 64
PlayResY: 64

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, \
Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, \
MarginR, MarginV, Encoding
Style: Default,Sans,20,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,2,2,2,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,{\\c&H0000FFFF&}ok
"""


@dataclass(frozen=True)
class Capabilities:
    version: str
    has_ass: bool
    has_libx264: bool
    render_ok: bool
    error: str = ""

    @property
    def usable(self) -> bool:
        return self.has_ass and self.has_libx264 and self.render_ok


@dataclass(frozen=True)
class FfmpegBinaries:
    ffmpeg: Path
    ffprobe: Path | None
    source: str  # "env" | "system" | "imageio"
    caps: Capabilities


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=PROBE_TIMEOUT_S,
        cwd=cwd,
        check=False,
        encoding="utf-8",
        errors="replace",
    )


def _has_token(listing: str, name: str) -> bool:
    """True if ``name`` is the second column of some line in ``ffmpeg -filters/-encoders`` output."""
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == name:
            return True
    return False


def _imageio_exe() -> Path | None:
    try:
        import imageio_ffmpeg
    except ImportError:
        return None
    try:
        exe = Path(imageio_ffmpeg.get_ffmpeg_exe())
    except RuntimeError:  # raised when the wheel has no binary for this platform
        return None
    return exe if exe.is_file() else None


def candidates() -> list[tuple[str, Path]]:
    """Candidate ffmpeg binaries in priority order, without duplicates."""
    found: list[tuple[str, Path]] = []
    env = os.environ.get("SNIPSCOUT_FFMPEG")
    if env:
        found.append(("env", Path(env)))
    system = shutil.which("ffmpeg")
    if system:
        found.append(("system", Path(system)))
    bundled = _imageio_exe()
    if bundled:
        found.append(("imageio", bundled))
    seen: set[Path] = set()
    unique = []
    for source, path in found:
        key = path.resolve() if path.exists() else path
        if key not in seen:
            seen.add(key)
            unique.append((source, path))
    return unique


def _probe_uncached(exe: Path) -> Capabilities:
    try:
        version_out = _run([str(exe), "-hide_banner", "-version"])
        filters = _run([str(exe), "-hide_banner", "-filters"]).stdout
        encoders = _run([str(exe), "-hide_banner", "-encoders"]).stdout
    except (OSError, subprocess.TimeoutExpired) as exc:
        return Capabilities("", False, False, False, error=f"{type(exc).__name__}: {exc}")
    version = (version_out.stdout.splitlines() or [""])[0]
    has_ass, has_x264 = _has_token(filters, "ass"), _has_token(encoders, "libx264")
    if not (has_ass and has_x264):
        return Capabilities(version, has_ass, has_x264, False, error="missing ass filter or libx264 encoder")
    # Real render. Relative file name + cwd is the pattern that avoids Windows path escaping in filters.
    with tempfile.TemporaryDirectory(prefix="snipscout-probe-") as tmp:
        work = Path(tmp)
        (work / "probe.ass").write_text(_PROBE_ASS, encoding="utf-8")
        try:
            r = _run(
                [
                    str(exe),
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=black:s=64x64:d=0.2",
                    "-vf",
                    "ass=probe.ass",
                    "-c:v",
                    "libx264",
                    "-f",
                    "null",
                    "-",
                ],
                cwd=work,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return Capabilities(version, True, True, False, error=f"{type(exc).__name__}: {exc}")
    ok = r.returncode == 0
    return Capabilities(version, True, True, ok, error="" if ok else r.stderr.strip()[-500:])


def _cache_key(exe: Path) -> str:
    st = exe.stat()
    return f"v{_CACHE_VERSION}|{exe.resolve()}|{st.st_size}|{st.st_mtime_ns}"


def _cache_file() -> Path:
    return cache_dir() / "ffmpeg_probe.json"


def _load_cache() -> dict[str, dict[str, object]]:
    try:
        data = json.loads(_cache_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def probe_capabilities(exe: Path, *, use_cache: bool = True) -> Capabilities:
    """Check ``exe`` for libass + libx264 and do a real render. Cached unless ``use_cache`` is False."""
    try:
        key = _cache_key(exe)
    except OSError as exc:
        return Capabilities("", False, False, False, error=f"not found: {exc}")
    if use_cache:
        hit = _load_cache().get(key)
        if hit is not None:
            try:
                return Capabilities(**hit)  # type: ignore[arg-type]
            except TypeError:
                pass  # stale schema; re-probe
    caps = _probe_uncached(exe)
    if use_cache and caps.usable:  # only cache successes; failures are retried next launch
        cache = _load_cache()
        cache[key] = asdict(caps)
        try:
            _cache_file().parent.mkdir(parents=True, exist_ok=True)
            _cache_file().write_text(json.dumps(cache, indent=1), encoding="utf-8")
        except OSError:
            pass  # cache is an optimisation only
    return caps


def find_ffprobe(ffmpeg: Path) -> Path | None:
    """ffprobe next to ffmpeg, else on PATH, else None (imageio-ffmpeg ships no ffprobe)."""
    suffix = ".exe" if ffmpeg.suffix.lower() == ".exe" else ""
    sibling = ffmpeg.with_name("ffprobe" + suffix)
    if ffmpeg.stem == "ffmpeg" and sibling.is_file():
        return sibling
    on_path = shutil.which("ffprobe")
    return Path(on_path) if on_path else None


def resolve_ffmpeg(*, use_cache: bool = True) -> FfmpegBinaries:
    """Return the first usable ffmpeg. Raises ``FfmpegMissingError`` listing everything tried."""
    tried: list[str] = []
    for source, exe in candidates():
        caps = probe_capabilities(exe, use_cache=use_cache)
        if caps.usable:
            return FfmpegBinaries(ffmpeg=exe, ffprobe=find_ffprobe(exe), source=source, caps=caps)
        tried.append(
            f"[{source}] {exe}: ass={caps.has_ass} libx264={caps.has_libx264} "
            f"render={caps.render_ok} {caps.error}".strip()
        )
    raise FfmpegMissingError(
        "No usable ffmpeg with libass and libx264 was found.",
        details="\n".join(tried) or "no candidates found",
    )
