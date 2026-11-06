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
