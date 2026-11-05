"""Validate and describe an input file. Uses ffprobe when present, otherwise PyAV
(imageio-ffmpeg ships no ffprobe; see docs/spike-report.md)."""

from __future__ import annotations

import json
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any

from clipforge.core.errors import UnsupportedMediaError
from clipforge.core.models import AudioTrack, MediaInfo

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a"}
SUPPORTED_EXTS = VIDEO_EXTS | AUDIO_EXTS
PROBE_TIMEOUT_S = 60
# Cover art / thumbnails show up as video streams with these codecs in audio files.
_STILL_CODECS = {"mjpeg", "png", "bmp", "gif"}


def _rate(value: str | None) -> float | None:
    if not value or value in {"0/0", "0"}:
        return None
    try:
        r = float(Fraction(value))
    except (ValueError, ZeroDivisionError):
        return None
    return r if r > 0 else None


def _norm_rotation(deg: float | int | None) -> int:
    if deg is None:
        return 0
    return int(round(float(deg) / 90.0) * 90) % 360


def _probe_ffprobe(ffprobe: Path, path: Path) -> MediaInfo:
    try:
        r = subprocess.run(
            [
                str(ffprobe),
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_S,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UnsupportedMediaError("Could not read this file.", details=str(exc)) from exc
    if r.returncode != 0:
        raise UnsupportedMediaError(
            "This file is not a video or audio we can read.", details=r.stderr[-1000:]
        )
    data = json.loads(r.stdout or "{}")
    return _from_ffprobe_json(path, data)


def _from_ffprobe_json(path: Path, data: dict[str, Any]) -> MediaInfo:
    streams = data.get("streams", [])
    fmt = data.get("format", {})
    video = next(
        (
            s
            for s in streams
            if s.get("codec_type") == "video"
            and s.get("codec_name") not in _STILL_CODECS
            and not s.get("disposition", {}).get("attached_pic")
        ),
        None,
    )
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    durations = [float(fmt["duration"])] if fmt.get("duration") not in (None, "N/A") else []
    durations += [float(s["duration"]) for s in streams if s.get("duration") not in (None, "N/A")]
    rotation = 0
    fps = vfr = None
    if video:
        for sd in video.get("side_data_list") or []:
            if "rotation" in sd:
                rotation = _norm_rotation(sd["rotation"])
        if not rotation and "rotate" in video.get("tags", {}):
            rotation = _norm_rotation(float(video["tags"]["rotate"]))
        avg, real = _rate(video.get("avg_frame_rate")), _rate(video.get("r_frame_rate"))
        fps = avg or real
        vfr = bool(avg and real and abs(avg - real) > 0.01 * real)
    return MediaInfo(
        path=path,
        size_bytes=path.stat().st_size,
        container=str(fmt.get("format_name", "")),
        duration=max(durations, default=0.0),
        has_video=video is not None,
        video_codec=video.get("codec_name") if video else None,
        width=video.get("width") if video else None,
        height=video.get("height") if video else None,
        fps=fps,
        variable_frame_rate=bool(vfr),
        rotation=rotation,
        audio_tracks=[
            AudioTrack(
                index=i,
                codec=s.get("codec_name"),
                channels=s.get("channels"),
                sample_rate=int(s["sample_rate"]) if s.get("sample_rate") else None,
                language=(s.get("tags", {}).get("language") or None),
            )
            for i, s in enumerate(audio)
        ],
    )


def _probe_pyav(path: Path) -> MediaInfo:
    import av

    try:
        container = av.open(str(path))
    except (av.FFmpegError, OSError) as exc:
        raise UnsupportedMediaError(
            "This file is not a video or audio we can read.", details=str(exc)
        ) from exc
    with container:
        video = next(
            (
                s
                for s in container.streams.video
                if s.codec_context.name not in _STILL_CODECS
                and not (s.disposition & av.stream.Disposition.attached_pic)
            ),
            None,
        )
        rotation = 0
        fps = vfr = None
        if video is not None:
            avg, guessed = video.average_rate, video.guessed_rate
            fps = float(avg) if avg else (float(guessed) if guessed else None)
            vfr = bool(avg and guessed and abs(float(avg) - float(guessed)) > 0.01 * float(guessed))
            try:  # rotation lives in the display matrix; PyAV exposes it on decoded frames
                frame = next(container.decode(video))
                rotation = _norm_rotation(getattr(frame, "rotation", 0))
            except (StopIteration, av.FFmpegError):
                pass
        duration = container.duration / 1e6 if container.duration else 0.0
        info = MediaInfo(
            path=path,
            size_bytes=path.stat().st_size,
            container=container.format.name,
            duration=duration,
            has_video=video is not None,
            video_codec=video.codec_context.name if video else None,
            width=video.codec_context.width if video else None,
            height=video.codec_context.height if video else None,
            fps=fps,
            variable_frame_rate=bool(vfr),
            rotation=rotation,
            audio_tracks=[
                AudioTrack(
                    index=i,
                    codec=s.codec_context.name,
                    channels=s.codec_context.channels,
                    sample_rate=s.codec_context.sample_rate,
                    language=s.metadata.get("language"),
                )
                for i, s in enumerate(container.streams.audio)
            ],
        )
    return info


def probe(path: Path, ffprobe: Path | None = None) -> MediaInfo:
    """Describe ``path``. Raises ``UnsupportedMediaError`` for missing, unsupported or unreadable files."""
    path = Path(path)
    if not path.is_file():
        raise UnsupportedMediaError("The file does not exist.", details=str(path))
    if path.suffix.lower() not in SUPPORTED_EXTS:
        raise UnsupportedMediaError(
            "Unsupported file type.",
            details=f"{path.suffix or '(none)'}; supported: {sorted(SUPPORTED_EXTS)}",
        )
    info = _probe_ffprobe(ffprobe, path) if ffprobe else _probe_pyav(path)
    if not info.audio_tracks and not info.has_video:
        raise UnsupportedMediaError("This file has no audio or video.", details=str(path))
    if info.duration <= 0:
        raise UnsupportedMediaError("Could not determine the duration of this file.", details=str(path))
    return info
