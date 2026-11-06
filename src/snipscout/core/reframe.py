"""Output geometry and ffmpeg filter chains for changing aspect ratio.

Modes: ``center`` (scale to cover + center crop, the default), ``face`` (scale to cover + crop centred on
the speaker's face, see ``core/faces.py``; fixed for the whole clip) and ``blur-pad`` (whole frame over a
blurred, zoomed copy of itself; kept for callers that ask for it, never chosen by default).
"""

from __future__ import annotations

from enum import StrEnum

from snipscout.core.models import AspectRatio, MediaInfo

AUDIO_ONLY_BG = "0x15112B"  # deep brand violet for audio-only sources


class ReframeMode(StrEnum):
    CENTER = "center"
    BLUR_PAD = "blur-pad"
    FACE = "face"


_TARGETS = {
    AspectRatio.VERTICAL: (1080, 1920),
    AspectRatio.SQUARE: (1080, 1080),
    AspectRatio.HORIZONTAL: (1920, 1080),
}


def _even(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


def output_size(media: MediaInfo, aspect: AspectRatio) -> tuple[int, int]:
    if aspect in _TARGETS:
        return _TARGETS[aspect]
    size = media.display_size or (1080, 1920)
    w, h = size
    scale = min(1.0, 1920 / max(w, h))  # cap the long side at 1920
    return _even(w * scale), _even(h * scale)


def default_mode(media: MediaInfo, aspect: AspectRatio) -> ReframeMode:
    """Always fill the whole output (scale to cover + crop): a vertical clip must be vertical video edge to
    edge, never a horizontal strip over a blurred background. ``render.for_clip`` moves the crop onto the
    speaker's face when one is steadily in view; otherwise the crop is centred."""
    return ReframeMode.CENTER


def _pan_expr(path: tuple[tuple[float, float], ...]) -> str:
    """ffmpeg expression of the focus x at time ``t``: piecewise linear between keyframes."""
    expr = f"{path[-1][1]:.4f}"
    for (t0, x0), (t1, x1) in reversed(list(zip(path, path[1:], strict=False))):
        slope = (x1 - x0) / max(t1 - t0, 1e-3)
        expr = f"if(lt(t\\,{t1:.3f})\\,{x0:.4f}+({slope:.5f})*(t-{t0:.3f})\\,{expr})"
    return expr


def video_filter(
    width: int,
    height: int,
    mode: ReframeMode,
    focus: tuple[float, float] | None = None,
    path: tuple[tuple[float, float], ...] | None = None,
) -> str:
    """Filter graph from input label [0:v] to an output ready for subtitles (label [base]).

    ``focus`` (FACE mode) is the face centre as fractions of the source frame; the crop window is
    centred on it and clamped inside the frame. With ``path`` ((seconds, x) keyframes from the clip start)
    the crop pans along it instead of staying fixed."""
    if mode == ReframeMode.FACE and focus is not None:
        fx, fy = (min(1.0, max(0.0, v)) for v in focus)
        fxe = f"({_pan_expr(path)})" if path and len(path) > 1 else f"{fx:.4f}"
        x = f"min(max({fxe}*iw-{width}/2\\,0)\\,iw-{width})"
        y = f"min(max({fy:.4f}*ih-{height}*0.4\\,0)\\,ih-{height})"  # face in the upper part of the frame
        return (
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}:{x}:{y},setsar=1,format=yuv420p[base]"
        )
    if mode == ReframeMode.BLUR_PAD:
        return (
            f"[0:v]split=2[bgsrc][fgsrc];"
            f"[bgsrc]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},"
            f"boxblur=luma_radius=min(h\\,w)/20:luma_power=2,eq=brightness=-0.08[bg];"
            f"[fgsrc]scale={width}:{height}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,format=yuv420p[base]"
        )
    return (
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1,format=yuv420p[base]"
    )
