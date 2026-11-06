"""Render one clip: cut, reframe, burn subtitles, encode H.264/AAC with +faststart.

ffmpeg runs with its working directory set to the clip's folder and receives *relative*
names in filter arguments (``ass=clip.ass:fontsdir=fonts``). This avoids the escaping problems
of Windows drive letters and backslashes inside filtergraphs.
"""

from __future__ import annotations

import dataclasses
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from snipscout.core.errors import FfmpegFailedError
from snipscout.core.faces import find_focus
from snipscout.core.models import Framing, MediaInfo
from snipscout.core.procs import CancelToken, run_ffmpeg
from snipscout.core.reframe import AUDIO_ONLY_BG, ReframeMode, video_filter
from snipscout.core.subtitles import FONTS_DIR

HW_ENCODERS = ("h264_nvenc", "h264_qsv", "h264_videotoolbox", "h264_amf")


@dataclass
class RenderOptions:
    width: int
    height: int
    mode: ReframeMode
    crf: int = 20
    preset: str = "veryfast"
    audio_track: int = 0
    loudnorm: bool = False
    hardware: bool = False  # try a hardware H.264 encoder first, fall back to libx264
    burn_subtitles: bool = True
    follow_face: bool = False  # when cropping a different shape, centre the crop on the speaker's face
    focus: tuple[float, float] | None = None  # set by for_clip() in FACE mode


def ensure_fonts(work_dir: Path) -> None:
    """Copy bundled fonts next to the subtitles so ``fontsdir=fonts`` is a short relative path."""
    dest = work_dir / "fonts"
    dest.mkdir(parents=True, exist_ok=True)
    for f in FONTS_DIR.glob("*.otf"):
        target = dest / f.name
        if not target.exists():
            shutil.copy2(f, target)


def available_hw_encoders(ffmpeg: Path) -> list[str]:
    try:
        out = subprocess.run(
            [str(ffmpeg), "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [e for e in HW_ENCODERS if f" {e} " in out]


def build_args(
    media: MediaInfo,
    start: float,
    end: float,
    ass_name: str | None,
    out_file: str,
    opts: RenderOptions,
    encoder: str = "libx264",
) -> list[str]:
    dur = max(0.1, end - start)
    args = ["-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(media.path)]
    if media.has_video:
        graph = video_filter(opts.width, opts.height, opts.mode, opts.focus)
    else:
        args += [
            "-f",
            "lavfi",
            "-t",
            f"{dur:.3f}",
            "-i",
            f"color=c={AUDIO_ONLY_BG}:s={opts.width}x{opts.height}:r=30",
        ]
        graph = "[1:v]format=yuv420p[base]"
    if ass_name and opts.burn_subtitles:
        graph += f";[base]ass={ass_name}:fontsdir=fonts[v]"
    else:
        graph += ";[base]null[v]"
    if media.variable_frame_rate or not media.has_video:
        graph = graph.removesuffix("[v]") + ",fps=30[v]"  # constant frame rate output
    args += ["-filter_complex", graph, "-map", "[v]"]
    if media.audio_tracks:
        track = opts.audio_track if 0 <= opts.audio_track < len(media.audio_tracks) else 0
        args += ["-map", f"0:a:{track}"]
        if opts.loudnorm:
            args += ["-af", "loudnorm=I=-14:TP=-1.5:LRA=11"]
        args += ["-c:a", "aac", "-b:a", "160k", "-ar", "48000"]
    if encoder == "libx264":
        args += ["-c:v", "libx264", "-preset", opts.preset, "-crf", str(opts.crf)]
    else:
        args += ["-c:v", encoder, "-b:v", "8M"]
    args += ["-pix_fmt", "yuv420p", "-movflags", "+faststart", "-shortest", out_file]
    return args


def crops(media: MediaInfo, opts: RenderOptions) -> bool:
    """True when the export crops part of the source frame (so where to crop matters)."""
    if opts.mode != ReframeMode.CENTER or not media.has_video or not media.display_size:
        return False
    sw, sh = media.display_size
    return abs((sw / sh) / (opts.width / opts.height) - 1) >= 0.05


def for_clip(
    ffmpeg: Path,
    media: MediaInfo,
    opts: RenderOptions,
    start: float,
    end: float,
    *,
    framing: Framing = Framing.AUTO,
    focus_x: float | None = None,
    cancel: CancelToken | None = None,
) -> RenderOptions:
    """Options for one clip when the crop cuts away part of the frame (e.g. 16:9 → 9:16):
    AUTO centres it on the speaker's face if one is steadily in view (and the project allows it), CENTER keeps
    the middle, MANUAL centres it on ``focus_x``."""
    if not crops(media, opts):
        return opts
    if framing == Framing.MANUAL and focus_x is not None:
        return dataclasses.replace(opts, mode=ReframeMode.FACE, focus=(focus_x, 0.4))
    if framing == Framing.CENTER or not opts.follow_face:
        return opts
    focus = find_focus(ffmpeg, media, start, end, cancel=cancel)
    if focus is None:
        return opts
    return dataclasses.replace(opts, mode=ReframeMode.FACE, focus=(focus.x, focus.y))


def render_clip(
    ffmpeg: Path,
    media: MediaInfo,
    start: float,
    end: float,
    work_dir: Path,
    out_path: Path,
    ass_name: str | None,
    opts: RenderOptions,
    *,
    on_progress: Callable[[float], None] | None = None,
    cancel: CancelToken | None = None,
) -> Path:
    """Render to ``out_path``. ``work_dir`` holds the .ass file and fonts (ffmpeg's cwd).
    Partial files are removed on failure."""
    work_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_path.resolve()
    if ass_name:
        ensure_fonts(work_dir)
    encoders = [*available_hw_encoders(ffmpeg), "libx264"] if opts.hardware else ["libx264"]
    tmp = out_path.with_name(out_path.stem + ".part.mp4")
    last_error: FfmpegFailedError | None = None
    try:
        for enc in encoders:
            try:
                run_ffmpeg(
                    ffmpeg,
                    build_args(media, start, end, ass_name, str(tmp), opts, enc),
                    cwd=work_dir,
                    duration=end - start,
                    on_progress=on_progress,
                    cancel=cancel,
                )
            except FfmpegFailedError as exc:
                last_error = exc  # hardware encoder unusable on this machine: try the next one
                continue
            tmp.replace(out_path)
            return out_path
        assert last_error is not None  # noqa: S101 - loop ran at least once
        raise last_error
    finally:
        tmp.unlink(missing_ok=True)


def render_still(
    ffmpeg: Path,
    media: MediaInfo,
    at: float,
    work_dir: Path,
    out_path: Path,
    ass_name: str | None,
    opts: RenderOptions,
) -> Path:
    """One JPEG frame at absolute time ``at`` with the same reframe and libass subtitles as the export.

    The ASS file must already be timed so that its 0 s is ``at`` (see ``subtitles.shift_words``)."""
    work_dir.mkdir(parents=True, exist_ok=True)
    if ass_name:
        ensure_fonts(work_dir)
    if media.has_video:
        args = ["-ss", f"{max(0.0, at):.3f}", "-i", str(media.path)]
        graph = video_filter(opts.width, opts.height, opts.mode, opts.focus)
    else:
        args = ["-f", "lavfi", "-i", f"color=c={AUDIO_ONLY_BG}:s={opts.width}x{opts.height}:r=30"]
        graph = "[0:v]format=yuv420p[base]"
    graph += f";[base]ass={ass_name}:fontsdir=fonts[v]" if ass_name else ";[base]null[v]"
    args += [
        "-filter_complex",
        graph,
        "-map",
        "[v]",
        "-frames:v",
        "1",
        "-q:v",
        "3",
        "-update",
        "1",
        str(out_path.resolve()),
    ]
    run_ffmpeg(ffmpeg, args, cwd=work_dir, timeout=60)
    return out_path
