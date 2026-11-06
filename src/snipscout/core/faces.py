"""Find where the speaker's face is in a clip, for face-aware vertical crops.

Uses YuNet (OpenCV Zoo, MIT, 230 KB, bundled in ``assets/models``) through onnxruntime on the CPU.
A clip is sampled at about one frame per second; the largest face in each frame is kept. If a face is
seen in most frames and stays in one place (one speaker, steady framing), its median position is the
crop focus. Otherwise there is no focus and the crop stays centred.
"""

from __future__ import annotations

import subprocess
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from snipscout.core.errors import FfmpegFailedError
from snipscout.core.models import MediaInfo
from snipscout.core.procs import CancelToken

MODEL = Path(__file__).resolve().parents[1] / "assets" / "models" / "face_detection_yunet_2023mar.onnx"
INPUT = 640  # the model's fixed input size (square)
STRIDES = (8, 16, 32)
MIN_SCORE = 0.6
MIN_PRESENCE = 0.5  # share of sampled frames that must show a face
MAX_SPREAD = 0.15  # interquartile range of face centres (fraction of width) for a "steady" speaker
MAX_SAMPLES = 40
_CACHE: OrderedDict[tuple[str, float, float, float], Focus | None] = OrderedDict()  # editor previews


@dataclass(frozen=True)
class Face:
    x: float  # box in pixels of the analysed frame
    y: float
    w: float
    h: float
    score: float


@dataclass(frozen=True)
class Focus:
    """Face centre as a fraction of the frame (0..1 from left/top)."""

    x: float
    y: float
    presence: float  # share of sampled frames with a face


@lru_cache(maxsize=1)
def _session() -> Any:
    import onnxruntime as ort

    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 2  # small model; leave the CPU to ffmpeg
    return ort.InferenceSession(str(MODEL), sess_options=opts, providers=["CPUExecutionProvider"])


def decode(outputs: dict[str, npt.NDArray[np.float32]], min_score: float = MIN_SCORE) -> list[Face]:
    """Turn YuNet's per-stride outputs into boxes (same maths as OpenCV's FaceDetectorYN), then NMS."""
    faces: list[Face] = []
    for s in STRIDES:
        cols = INPUT // s
        cls = np.clip(outputs[f"cls_{s}"][0, :, 0], 0, 1)
        obj = np.clip(outputs[f"obj_{s}"][0, :, 0], 0, 1)
        score = np.sqrt(cls * obj)
        for idx in np.nonzero(score >= min_score)[0]:
            r, c = divmod(int(idx), cols)
            dx, dy, dw, dh = (float(v) for v in outputs[f"bbox_{s}"][0, idx])
            cx, cy = (c + dx) * s, (r + dy) * s
            w, h = float(np.exp(dw)) * s, float(np.exp(dh)) * s
            faces.append(Face(cx - w / 2, cy - h / 2, w, h, float(score[idx])))
    return _nms(faces)


def _nms(faces: list[Face], iou: float = 0.3) -> list[Face]:
    kept: list[Face] = []
    for f in sorted(faces, key=lambda f: -f.score):
        if all(_iou(f, k) < iou for k in kept):
            kept.append(f)
    return kept


def _iou(a: Face, b: Face) -> float:
    ix = max(0.0, min(a.x + a.w, b.x + b.w) - max(a.x, b.x))
    iy = max(0.0, min(a.y + a.h, b.y + b.h) - max(a.y, b.y))
    inter = ix * iy
    return inter / max(a.w * a.h + b.w * b.h - inter, 1e-6)


def detect(frame_bgr: npt.NDArray[np.uint8]) -> list[Face]:
    """Faces in one BGR frame whose width is INPUT and height at most INPUT (padded at the bottom)."""
    h, w = frame_bgr.shape[:2]
    canvas = np.zeros((INPUT, INPUT, 3), dtype=np.float32)
    canvas[:h, :w] = frame_bgr
    blob = canvas.transpose(2, 0, 1)[None]
    sess = _session()
    names = [o.name for o in sess.get_outputs()]
    values = sess.run(names, {sess.get_inputs()[0].name: blob})
    return decode(dict(zip(names, values, strict=True)))


def summarize(per_frame: list[list[Face]], frame_w: int, frame_h: int) -> Focus | None:
    """Focus from the largest face of each frame, or None when the face is missing or moves around."""
    if not per_frame:
        return None
    centres = [
        ((f.x + f.w / 2) / frame_w, (f.y + f.h / 2) / frame_h)
        for f in (max(fs, key=lambda f: f.w * f.h) for fs in per_frame if fs)
    ]
    presence = len(centres) / len(per_frame)
    if presence < MIN_PRESENCE:
        return None
    xs = np.array([c[0] for c in centres])
    if float(np.percentile(xs, 75) - np.percentile(xs, 25)) > MAX_SPREAD:
        return None  # two people, or a moving camera: a fixed crop would cut someone off
    ys = np.array([c[1] for c in centres])
    return Focus(float(np.median(xs)), float(np.median(ys)), round(presence, 2))


def find_focus(
    ffmpeg: Path, media: MediaInfo, start: float, end: float, *, cancel: CancelToken | None = None
) -> Focus | None:
    """Sample the clip, detect faces and return a steady focus point (or None). Cached per file and range."""
    if not media.has_video or not media.display_size:
        return None
    try:
        key = (str(media.path), media.path.stat().st_mtime, round(start, 1), round(end, 1))
    except OSError:
        return None
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    focus = _find_focus(ffmpeg, media, start, end, cancel)
    _CACHE[key] = focus
    while len(_CACHE) > 64:
        _CACHE.popitem(last=False)
    return focus


def _find_focus(
    ffmpeg: Path, media: MediaInfo, start: float, end: float, cancel: CancelToken | None
) -> Focus | None:
    assert media.display_size is not None  # noqa: S101 - checked by the caller
    sw, sh = media.display_size
    fw = INPUT
    fh = min(INPUT, max(2, int(round(sh * INPUT / sw / 2)) * 2))
    dur = max(0.5, end - start)
    fps = min(1.0, MAX_SAMPLES / dur)
    args = [
        str(ffmpeg), "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}",
        "-i", str(media.path), "-map", "0:v:0", "-an",
        "-vf", f"fps={fps:.4f},scale={fw}:{fh}", "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1",
    ]  # fmt: skip
    if cancel:
        cancel.raise_if_cancelled()
    try:
        out = subprocess.run(args, capture_output=True, timeout=120, check=True)  # noqa: S603 - arg list, no shell
    except subprocess.CalledProcessError as exc:
        raise FfmpegFailedError(
            "Could not read frames for face detection.", details=exc.stderr[-500:].decode("utf-8", "replace")
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise FfmpegFailedError("Reading frames for face detection timed out.") from exc
    size = fw * fh * 3
    frames = [
        np.frombuffer(out.stdout, dtype=np.uint8, count=size, offset=i * size).reshape(fh, fw, 3)
        for i in range(len(out.stdout) // size)
    ]
    per_frame = []
    for frame in frames:
        if cancel:
            cancel.raise_if_cancelled()
        per_frame.append(detect(frame))
    return summarize(per_frame, fw, fh)
