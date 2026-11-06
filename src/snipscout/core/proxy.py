"""Playback proxy for the in-app preview: a small VP9/Opus WebM of the whole source.

Used only when the window cannot play the original file — e.g. Qt WebEngine on Linux has no H.264,
and Windows WebView2 often has no HEVC (iPhone videos). WebM/VP9 plays in every webview SnipScout
uses. Exports always read the original file; the proxy is only for watching while editing. It keeps
the source's timeline (same duration and timestamps), so the editor needs no time mapping.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from snipscout.core.models import MediaInfo
from snipscout.core.procs import CancelToken, run_ffmpeg

HEIGHT = 360  # enough to judge framing and lip sync; fast to encode on a laptop CPU


def proxy_args(media: MediaInfo, out: Path, *, audio_track: int = 0) -> list[str]:
    args = ["-i", str(media.path), "-map", "0:v:0?", "-map", f"0:a:{audio_track}?"]
    args += [
        "-vf",
        f"scale=-2:'min({HEIGHT},ih)'",
        "-c:v",
        "libvpx-vp9",
        "-deadline",
        "realtime",
        "-cpu-used",
        "8",
    ]
    args += ["-row-mt", "1", "-b:v", "0", "-crf", "40", "-pix_fmt", "yuv420p"]
    args += ["-c:a", "libopus", "-b:a", "64k", "-ac", "2", "-f", "webm", str(out)]
    return args


def build_proxy(
    ffmpeg: Path,
    media: MediaInfo,
    out: Path,
    *,
    audio_track: int = 0,
    on_progress: Callable[[float], None] | None = None,
    cancel: CancelToken | None = None,
) -> Path:
    """Encode the proxy to ``out`` (written to a temporary name first, so a half file is never served)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + ".part.webm")
    try:
        run_ffmpeg(
            ffmpeg,
            proxy_args(media, tmp, audio_track=audio_track),
            duration=media.duration,
            on_progress=on_progress,
            cancel=cancel,
        )
        tmp.replace(out)
    finally:
        tmp.unlink(missing_ok=True)
    return out
