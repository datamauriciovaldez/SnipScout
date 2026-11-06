"""Clips, transcript, thumbnails, preview frames, source media and waveform."""

from __future__ import annotations

import threading
import uuid
from typing import Any

from fastapi import FastAPI
from fastapi.responses import (
    FileResponse,
)

from snipscout.core import audio
from snipscout.core.errors import SnipScoutError, UnsupportedMediaError
from snipscout.core.models import (
    ClipSet,
)
from snipscout.core.procs import run_ffmpeg
from snipscout.core.proxy import build_proxy
from snipscout.core.scoring import ScoringConfig
from snipscout.core.segment import segment
from snipscout.core.storage import ProjectNotFoundError
from snipscout.web.common import ApiError, ClipPatch, Context, PreviewFrameRequest

PROXY_NAME = "preview.webm"  # inside the project folder; regenerable, removed by "Free up space"


def register(app: FastAPI, ctx: Context) -> None:  # noqa: C901 - routes as closures over ctx
    # --- clips ------------------------------------------------------------------------------------
    @app.get("/api/v1/projects/{pid}/clips")
    def get_clips(pid: str) -> dict[str, Any]:
        """Clips plus each signal's contribution in score points (they add up to the score)."""
        ctx.store.load(pid)
        clips = ctx.store.load_clips(pid) or ClipSet()
        weights = ScoringConfig.load().weights
        total_w = sum(weights.values()) or 1.0
        out = clips.model_dump(mode="json")
        for clip in out["clips"]:
            clip["contributions"] = {
                k: round(weights.get(k, 0.0) * v / total_w * 100, 1) for k, v in clip["signals"].items()
            }
        return out

    @app.get("/api/v1/projects/{pid}/transcript")
    def get_transcript(pid: str) -> dict[str, Any]:
        """Words (for subtitle editing) and sentences (for snapping clip edges)."""
        p = ctx.store.load(pid)
        tr = ctx.store.load_transcript(pid)
        if tr is None:
            raise ApiError("Analyze the video first.", details="no transcript yet")
        sentences = segment(tr.words, language=tr.language)
        return {
            "language": tr.language,
            "complete": tr.complete,
            "duration": p.source.duration,
            "words": [w.model_dump(mode="json") for w in tr.words],
            "sentences": [
                {
                    "start": s.start,
                    "end": s.end,
                    "text": s.text,
                    "word_start": s.word_start,
                    "word_end": s.word_end,
                }
                for s in sentences
            ],
        }

    @app.patch("/api/v1/projects/{pid}/clips/{cid}")
    def patch_clip(pid: str, cid: str, body: ClipPatch) -> dict[str, Any]:
        p = ctx.store.load(pid)
        clips = ctx.store.load_clips(pid) or ClipSet()
        clip = next((c for c in clips.clips if c.id == cid), None)
        if clip is None:
            raise ProjectNotFoundError("Unknown clip.", details=cid)
        changes = body.model_dump(exclude_unset=True)
        start, end = changes.get("start", clip.start), changes.get("end", clip.end)
        if not 0 <= start < end <= p.source.duration + 0.01 or end - start < 1.0:
            raise ApiError("Invalid clip range.", details=f"start={start} end={end}")
        if "subtitle_style" in changes and changes["subtitle_style"] is not None:
            from snipscout.core.subtitles import PRESETS

            if changes["subtitle_style"] not in PRESETS:
                raise ApiError("Unknown subtitle style.", details=changes["subtitle_style"])
        for key, value in changes.items():
            setattr(clip, key, value)
        ctx.store.save_clips(pid, clips)
        return clip.model_dump(mode="json")

    @app.get("/api/v1/projects/{pid}/clips/{cid}/thumbnail")
    def thumbnail(pid: str, cid: str) -> FileResponse:
        p = ctx.store.load(pid)
        clips = ctx.store.load_clips(pid) or ClipSet()
        clip = next((c for c in clips.clips if c.id == cid), None)
        if clip is None:
            raise ProjectNotFoundError("Unknown clip.", details=cid)
        if not p.source.has_video:
            raise UnsupportedMediaError("Audio-only project: no thumbnail.")
        at = (clip.start + clip.end) / 2
        out = ctx.store.project_dir(pid) / "thumbs" / f"{cid}_{int(at * 10)}.jpg"
        if not out.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
            run_ffmpeg(
                ctx.require_ffmpeg().ffmpeg,
                [
                    "-ss",
                    f"{at:.2f}",
                    "-i",
                    str(p.source.path),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=-2:360",
                    "-q:v",
                    "4",
                    "-update",
                    "1",
                    str(out),
                ],
                timeout=60,
            )
        return FileResponse(out, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})

    @app.post("/api/v1/projects/{pid}/clips/{cid}/preview-frame")
    def preview_frame(pid: str, cid: str, body: PreviewFrameRequest) -> FileResponse:
        """One real frame (ffmpeg + libass, same reframe as the export) for the editor's current draft."""
        from snipscout.core.render import for_clip, render_still
        from snipscout.core.subtitles import PRESETS, build_ass, clip_words, shift_words

        p = ctx.store.load(pid)
        clips = ctx.store.load_clips(pid) or ClipSet()
        clip = next((c for c in clips.clips if c.id == cid), None)
        tr = ctx.store.load_transcript(pid)
        if clip is None or tr is None:
            raise ProjectNotFoundError("Unknown clip.", details=cid)
        changes = body.model_dump(exclude_unset=True, exclude={"at"})
        if changes.get("subtitle_style") is not None and changes["subtitle_style"] not in PRESETS:
            raise ApiError("Unknown subtitle style.", details=changes["subtitle_style"])
        draft = clip.model_copy(update={k: v for k, v in changes.items() if v is not None})
        if not 0 <= body.at <= p.source.duration:
            raise ApiError("Time outside the video.", details=str(body.at))
        pipe = ctx.pipeline()
        opts = pipe.render_options(p)
        words = shift_words(clip_words(tr.words, draft), draft.start - body.at)  # ASS 0 s == `at`
        work = ctx.store.project_dir(pid) / "preview"
        for old in work.glob("frame_*.jpg"):
            old.unlink(missing_ok=True)
        tag = uuid.uuid4().hex[:8]
        ass_name = f"frame_{tag}.ass"
        work.mkdir(parents=True, exist_ok=True)
        (work / ass_name).write_text(
            build_ass(
                words,
                draft.subtitle_style or p.settings.subtitle_style,
                opts.width,
                opts.height,
                vertical=opts.height > opts.width,
            ),
            encoding="utf-8",
        )
        ff = ctx.require_ffmpeg().ffmpeg
        opts = for_clip(ff, p.source, opts, draft.start, draft.end)
        out = render_still(ff, p.source, body.at, work, work / f"frame_{tag}.jpg", ass_name, opts)
        (work / ass_name).unlink(missing_ok=True)
        return FileResponse(out, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    # --- media ------------------------------------------------------------------------------------
    @app.get("/api/v1/projects/{pid}/media")
    def media(pid: str, variant: str = "original") -> FileResponse:
        """The source file, or (``variant=proxy``) the WebM playback proxy once it is ready."""
        p = ctx.store.load(pid)
        if variant == "proxy":
            proxy = ctx.store.project_dir(pid) / PROXY_NAME
            if not proxy.is_file():
                raise ApiError("The preview copy is not ready yet.", details=pid)
            return FileResponse(proxy, media_type="video/webm")
        if not p.source.path.is_file():
            raise UnsupportedMediaError("The original file is no longer there.", details=str(p.source.path))
        return FileResponse(p.source.path)  # Starlette answers Range requests with 206

    def _proxy_state(pid: str) -> dict[str, Any]:
        if (ctx.store.project_dir(pid) / PROXY_NAME).is_file():
            return {"state": "ready", "progress": 1.0}
        st = ctx.proxies.get(pid)
        return dict(st) if st else {"state": "none", "progress": 0.0}

    @app.get("/api/v1/projects/{pid}/media/proxy")
    def proxy_status(pid: str) -> dict[str, Any]:
        ctx.store.load(pid)
        return _proxy_state(pid)

    @app.post("/api/v1/projects/{pid}/media/proxy", status_code=202)
    def proxy_start(pid: str) -> dict[str, Any]:
        """Start encoding the playback proxy (the window could not play the original). Idempotent."""
        p = ctx.store.load(pid)
        ff = ctx.require_ffmpeg().ffmpeg
        with ctx.proxies_lock:
            st = _proxy_state(pid)
            if st["state"] in {"ready", "working"} or not p.source.has_video:
                return st
            ctx.proxies[pid] = {"state": "working", "progress": 0.0}

        def work() -> None:
            def progress(f: float) -> None:
                ctx.proxies[pid] = {"state": "working", "progress": round(f, 3)}

            try:
                build_proxy(
                    ff,
                    p.source,
                    ctx.store.project_dir(pid) / PROXY_NAME,
                    audio_track=p.settings.audio_track,
                    on_progress=progress,
                )
                ctx.proxies.pop(pid, None)
            except SnipScoutError as exc:
                ctx.proxies[pid] = {"state": "error", "progress": 0.0, "error_code": exc.code}

        threading.Thread(target=work, name=f"proxy-{pid}", daemon=True).start()
        return {"state": "working", "progress": 0.0}

    @app.get("/api/v1/projects/{pid}/waveform")
    def waveform(pid: str, points: int = 800, start: float = 0.0, end: float | None = None) -> dict[str, Any]:
        """Waveform peaks for the whole file or for [start, end) (zoomed timeline).
        Heights are normalised on the whole file so they don't change with zoom."""
        import numpy as np

        ctx.store.load(pid)
        points = max(10, min(points, 6000))
        wav = ctx.store.audio_path(pid)
        if not wav.exists():
            raise ApiError("Analyze the video first.", details="no audio extracted yet")
        cache = ctx.store.project_dir(pid) / f"envelope_{wav.stat().st_mtime_ns}.npy"
        if cache.exists():
            env = np.load(cache)
        else:
            env = audio.rms_envelope_file(wav)
            for old in ctx.store.project_dir(pid).glob("envelope_*.npy"):
                old.unlink(missing_ok=True)
            np.save(cache, env)
        duration = audio.wav_duration(wav)
        start = max(0.0, min(start, duration))
        stop = duration if end is None else max(start, min(end, duration))
        top = float(np.percentile(env, 99)) if len(env) else 1.0
        peaks = audio.envelope_peaks(env, points=points, start=start, end=stop, top=top or 1.0)
        return {"duration": duration, "start": start, "end": stop, "points": len(peaks), "peaks": peaks}
