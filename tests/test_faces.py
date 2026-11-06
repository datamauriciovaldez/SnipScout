"""Face-aware reframing. CI has no real faces, so detection maths, the decision rule and the ffmpeg crop
are tested separately; the bundled model is loaded and run on a blank frame."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

from snipscout.core import faces
from snipscout.core.binaries import FfmpegBinaries
from snipscout.core.faces import Face, Focus, decode, summarize
from snipscout.core.reframe import ReframeMode, video_filter
from snipscout.core.render import RenderOptions, for_clip, render_still


def _outputs() -> dict[str, np.ndarray]:
    out: dict[str, np.ndarray] = {}
    for s in faces.STRIDES:
        n = (faces.INPUT // s) ** 2
        out[f"cls_{s}"] = np.zeros((1, n, 1), np.float32)
        out[f"obj_{s}"] = np.zeros((1, n, 1), np.float32)
        out[f"bbox_{s}"] = np.zeros((1, n, 4), np.float32)
        out[f"kps_{s}"] = np.zeros((1, n, 10), np.float32)
    return out


def test_decode_matches_yunet_geometry_and_nms() -> None:
    out = _outputs()
    cols = faces.INPUT // 16
    idx = 10 * cols + 20  # row 10, column 20 at stride 16
    out["cls_16"][0, idx, 0] = out["obj_16"][0, idx, 0] = 0.9
    out["bbox_16"][0, idx] = [0.5, 0.5, np.log(4), np.log(5)]  # centre (20.5, 10.5) cells, 64x80 px
    out["cls_16"][0, idx + 1, 0] = out["obj_16"][0, idx + 1, 0] = 0.8  # overlapping duplicate → suppressed
    out["bbox_16"][0, idx + 1] = [0.0, 0.5, np.log(4), np.log(5)]
    found = decode(out)
    assert len(found) == 1
    f = found[0]
    assert (round(f.x), round(f.y), round(f.w), round(f.h)) == (296, 128, 64, 80)
    assert f.score == pytest.approx(0.9)


def test_summarize_needs_one_steady_face() -> None:
    def face(cx: float) -> Face:
        return Face(cx * 640 - 20, 100, 40, 50, 0.9)

    steady = [[face(0.3)], [face(0.31)], [], [face(0.29), Face(500, 100, 10, 10, 0.7)]]
    focus = summarize(steady, 640, 360)
    assert focus is not None and focus.x == pytest.approx(0.3, abs=0.01) and focus.presence == 0.75
    assert summarize([[face(0.2)], [face(0.8)], [face(0.2)], [face(0.8)]], 640, 360) is None  # two people
    assert summarize([[face(0.3)], [], [], []], 640, 360) is None  # rarely visible
    assert summarize([], 640, 360) is None


def test_bundled_model_runs_on_cpu() -> None:
    assert faces.MODEL.is_file()
    assert faces.detect(np.full((360, 640, 3), 128, np.uint8)) == []


def test_face_crop_filter_follows_focus(ff: FfmpegBinaries, tmp_path: Path) -> None:
    """Left half red, right half blue: focusing at x=0.1 must give a mostly red vertical frame."""
    src = tmp_path / "split.mp4"
    subprocess.run(
        [str(ff.ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "color=c=red:s=960x1080:d=1",
         "-f", "lavfi", "-i", "color=c=blue:s=960x1080:d=1",
         "-filter_complex", "[0:v][1:v]hstack", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)],
        check=True, timeout=60,
    )  # fmt: skip
    from snipscout.core.ingest import probe

    media = probe(src, ff.ffprobe)
    for fx, red_expected in ((0.1, True), (0.9, False)):
        opts = RenderOptions(width=360, height=640, mode=ReframeMode.FACE, focus=(fx, 0.5))
        out = render_still(ff.ffmpeg, media, 0.2, tmp_path / "w", tmp_path / f"f{fx}.jpg", None, opts)
        raw = subprocess.run(
            [str(ff.ffmpeg), "-hide_banner", "-loglevel", "error", "-i", str(out),
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            capture_output=True, check=True, timeout=30,
        ).stdout  # fmt: skip
        rgb = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(int)
        assert bool(rgb[:, 0].mean() > rgb[:, 2].mean()) == red_expected
    assert "crop=360:640:min(max(0.1000*iw-360/2\\,0)\\,iw-360)" in video_filter(
        360, 640, ReframeMode.FACE, (0.1, 0.5)
    )


def test_for_clip_follows_face_only_when_cropping(
    monkeypatch: pytest.MonkeyPatch, video_mp4: Path, ff: FfmpegBinaries
) -> None:
    from snipscout.core.ingest import probe

    media = probe(video_mp4, ff.ffprobe)
    monkeypatch.setattr("snipscout.core.render.find_focus", lambda *a, **k: Focus(0.25, 0.4, 1.0))
    crop = RenderOptions(width=1080, height=1920, mode=ReframeMode.CENTER, follow_face=True)
    assert for_clip(ff.ffmpeg, media, crop, 0, 3).mode == ReframeMode.FACE
    assert for_clip(ff.ffmpeg, media, crop, 0, 3).focus == (0.25, 0.4)
    off = RenderOptions(width=1080, height=1920, mode=ReframeMode.CENTER, follow_face=False)
    assert for_clip(ff.ffmpeg, media, off, 0, 3) is off
    same_shape = RenderOptions(width=640, height=480, mode=ReframeMode.CENTER, follow_face=True)  # 4:3 too
    assert for_clip(ff.ffmpeg, media, same_shape, 0, 3) is same_shape
    pad = RenderOptions(width=1080, height=1920, mode=ReframeMode.BLUR_PAD, follow_face=True)
    assert for_clip(ff.ffmpeg, media, pad, 0, 3) is pad  # an explicit blur-pad request is respected
    monkeypatch.setattr("snipscout.core.render.find_focus", lambda *a, **k: None)
    assert for_clip(ff.ffmpeg, media, crop, 0, 3).mode == ReframeMode.CENTER  # no clear face: centred crop


def test_for_clip_honours_per_clip_framing(
    monkeypatch: pytest.MonkeyPatch, video_mp4: Path, ff: FfmpegBinaries
) -> None:
    from snipscout.core.ingest import probe
    from snipscout.core.models import Framing

    media = probe(video_mp4, ff.ffprobe)
    monkeypatch.setattr("snipscout.core.render.find_focus", lambda *a, **k: Focus(0.25, 0.4, 1.0))
    crop = RenderOptions(width=1080, height=1920, mode=ReframeMode.CENTER, follow_face=True)
    assert for_clip(ff.ffmpeg, media, crop, 0, 3, framing=Framing.CENTER) is crop
    manual = for_clip(ff.ffmpeg, media, crop, 0, 3, framing=Framing.MANUAL, focus_x=0.8)
    assert manual.mode == ReframeMode.FACE and manual.focus == (0.8, 0.4)
    no_face_project = RenderOptions(width=1080, height=1920, mode=ReframeMode.CENTER, follow_face=False)
    assert for_clip(ff.ffmpeg, media, no_face_project, 0, 3, framing=Framing.MANUAL, focus_x=0.1).focus == (
        0.1,
        0.4,
    )


def test_moving_speaker_gets_a_smooth_pan_path() -> None:
    from snipscout.core.faces import path_at

    def face(cx: float) -> Face:
        return Face(cx * 640 - 20, 100, 40, 50, 0.9)

    moving = [[face(0.2 + 0.02 * i)] for i in range(20)]  # walks right at 0.02 width/s
    moving[7] = []  # a missed detection is interpolated
    focus = summarize(moving, 640, 360, fps=1.0)
    assert focus is not None and focus.path is not None and len(focus.path) == 20
    xs = [x for _, x in focus.path]
    assert all(b >= a - 1e-9 for a, b in zip(xs, xs[1:], strict=False))  # monotonic, no jitter
    assert path_at(focus.path, 10.0) == pytest.approx(0.4, abs=0.03)
    assert max(abs(b - a) for a, b in zip(xs, xs[1:], strict=False)) <= 0.1 + 1e-9  # speed limit
    turns = [[face(0.2)], [face(0.8)]] * 10  # two people taking turns: jumps, not a walk
    assert summarize(turns, 640, 360, fps=1.0) is None


def test_pan_path_moves_the_crop_over_time(ff: FfmpegBinaries, tmp_path: Path) -> None:
    """Left half red, right half blue; the path pans from x=0.1 to x=0.9: first frame red, last frame blue."""
    from snipscout.core.ingest import probe
    from snipscout.core.render import at_time, render_clip

    src = tmp_path / "split.mp4"
    subprocess.run(
        [str(ff.ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "color=c=red:s=960x1080:d=3",
         "-f", "lavfi", "-i", "color=c=blue:s=960x1080:d=3",
         "-filter_complex", "[0:v][1:v]hstack", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)],
        check=True, timeout=60,
    )  # fmt: skip
    media = probe(src, ff.ffprobe)
    path = ((0.0, 0.1), (1.0, 0.1), (2.0, 0.9), (3.0, 0.9))
    opts = RenderOptions(width=180, height=320, mode=ReframeMode.FACE, focus=(0.5, 0.5), path=path)
    out = render_clip(ff.ffmpeg, media, 0.0, 3.0, tmp_path / "w", tmp_path / "pan.mp4", None, opts)

    def mean_rgb(at: float) -> np.ndarray:
        raw = subprocess.run(
            [str(ff.ffmpeg), "-hide_banner", "-loglevel", "error", "-ss", str(at), "-i", str(out),
             "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            capture_output=True, check=True, timeout=30,
        ).stdout  # fmt: skip
        return np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(int).mean(axis=0)

    start, end = mean_rgb(0.2), mean_rgb(2.7)
    assert start[0] > start[2] and end[2] > end[0]
    assert at_time(opts, 2.5).focus == (0.9, 0.5) and at_time(opts, 2.5).path is None
