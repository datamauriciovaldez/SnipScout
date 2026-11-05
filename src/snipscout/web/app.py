"""Local HTTP API (/api/v1) + static frontend.

Security model (spec 5.6): bound to 127.0.0.1 on a random free port; a per-launch session token is
handed to the window once (``/?t=TOKEN``) and kept in an HttpOnly, SameSite=Strict cookie. Every
/api request needs that cookie (or the ``X-SnipScout-Token`` header). Host and Origin headers are
checked to block DNS-rebinding and cross-site requests. No CORS.
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import queue
import secrets
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from snipscout import __version__
from snipscout.config import cache_dir, data_dir, default_output_dir, is_offline, models_dir, output_dir
from snipscout.core import audio, ingest, modelstore
from snipscout.core.binaries import FfmpegBinaries
from snipscout.core.errors import (
    CancelledError,
    FfmpegMissingError,
    ModelDownloadError,
    NoSpeechError,
    OfflineError,
    SnipScoutError,
    UnsupportedMediaError,
)
from snipscout.core.models import (
    AspectRatio,
    ClipLength,
    ClipSet,
    JobEvent,
    Project,
    ProjectSettings,
)
from snipscout.core.pipeline import Pipeline
from snipscout.core.preferences import Preferences, Quality, load_preferences, save_preferences
from snipscout.core.procs import CancelToken, run_ffmpeg
from snipscout.core.scoring import ScoringConfig
from snipscout.core.segment import segment
from snipscout.core.storage import ProjectNotFoundError, ProjectStore, slugify
from snipscout.core.transcribe import SpeechModel, estimate_seconds, load_model, measured_rtf
from snipscout.web.jobs import JobBusyError, JobManager

STATIC = Path(__file__).parent / "static"
COOKIE = "snipscout_session"
TOKEN_HEADER = "x-snipscout-token"  # noqa: S105 - header name, not a secret
MAX_UPLOAD_BYTES = 20 * 1024**3  # 20 GB
SSE_KEEPALIVE_S = 15.0

_STATUS = {
    ProjectNotFoundError: 404,
    UnsupportedMediaError: 400,
    NoSpeechError: 422,
    JobBusyError: 409,
    CancelledError: 409,
    OfflineError: 503,
    FfmpegMissingError: 503,
    ModelDownloadError: 502,
}


class ApiError(SnipScoutError):
    """Request-level validation error (bad field values)."""

    code = "bad_request"


class Context:
    """Everything the routes need; created once per server."""

    def __init__(
        self,
        store: ProjectStore,
        binaries: FfmpegBinaries | None,
        token: str,
        *,
        model_loader: Callable[[str], SpeechModel] = load_model,
        uploads_dir: Path | None = None,
    ) -> None:
        self.store = store
        self.binaries = binaries
        self.token = token
        self.jobs = JobManager()
        self.model_loader = model_loader
        self.uploads_dir = uploads_dir or (data_dir() / "uploads")
        self.allowed_hosts: set[str] = set()  # filled by the launcher with "127.0.0.1:PORT" etc.

    def require_ffmpeg(self) -> FfmpegBinaries:
        if self.binaries is None:
            raise FfmpegMissingError("ffmpeg with subtitle support is not available.")
        return self.binaries

    def pipeline(self) -> Pipeline:
        return Pipeline(self.store, self.require_ffmpeg(), model_loader=self.model_loader)


# --- request bodies -------------------------------------------------------------------------------


class SettingsPatch(BaseModel):
    clip_length: ClipLength | None = None
    aspect: AspectRatio | None = None
    subtitle_style: str | None = None
    language: str | None = None
    model: str | None = None
    audio_track: int | None = Field(default=None, ge=0, le=31)
    quick_analysis: bool | None = None


class CreateProject(BaseModel):
    path: str
    settings: SettingsPatch | None = None


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    settings: SettingsPatch | None = None


class ClipPatch(BaseModel):
    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, ge=0)
    included: bool | None = None
    title: str | None = Field(default=None, max_length=300)
    subtitle_style: str | None = None
    text_overrides: dict[int, str] | None = None


class RenderRequest(BaseModel):
    out_dir: str | None = None
    clip_ids: list[str] | None = Field(default=None, max_length=100)
    hardware: bool | None = None  # None = use the user's preference
    loudnorm: bool | None = None


class PreviewFrameRequest(BaseModel):
    at: float = Field(ge=0)
    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, ge=0)
    subtitle_style: str | None = None
    text_overrides: dict[int, str] | None = None


class SettingsUpdate(BaseModel):
    output_dir: str | None = None  # "" resets to the default folder
    quality: Quality | None = None
    hardware: bool | None = None
    loudnorm: bool | None = None


class DownloadRequest(BaseModel):
    model: str = modelstore.DEFAULT_MODEL


# --- helpers --------------------------------------------------------------------------------------


def _apply_settings(current: ProjectSettings, patch: SettingsPatch | None) -> ProjectSettings:
    if patch is None:
        return current
    data = current.model_dump()
    data.update({k: v for k, v in patch.model_dump(exclude_unset=True).items()})
    if data.get("model") not in modelstore.MODELS:
        raise ApiError("Unknown model.", details=str(data.get("model")))
    return ProjectSettings.model_validate(data)


def _project_json(ctx: Context, p: Project) -> dict[str, Any]:
    out: dict[str, Any] = p.model_dump(mode="json")
    out["job"] = None
    job = ctx.jobs.get(p.id)
    if job and job.running:
        out["job"] = {"kind": job.kind, "last": job.last.model_dump(mode="json") if job.last else None}
    clips = ctx.store.load_clips(p.id)
    out["clips_total"] = len(clips.clips) if clips else 0
    out["clips_included"] = sum(c.included for c in clips.clips) if clips else 0
    out["estimate_s"] = round(
        estimate_seconds(
            min(p.source.duration, 600) if p.settings.quick_analysis else p.source.duration, p.settings.model
        )
    )
    return out


def _sse(event: JobEvent | dict[str, Any], name: str = "progress") -> str:
    data = event.model_dump_json() if isinstance(event, JobEvent) else json.dumps(event, ensure_ascii=False)
    return f"event: {name}\ndata: {data}\n\n"


class RevealError(SnipScoutError):
    code = "reveal_failed"


def _reveal(path: Path) -> None:
    """Open a folder in the OS file manager (argument list, never a shell)."""
    try:
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606 - opens a folder the app created (mypy narrows by platform)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])  # noqa: S607
        else:
            subprocess.Popen(["xdg-open", str(path)])  # noqa: S607
    except OSError as exc:  # no file manager available (e.g. a minimal Linux install)
        raise RevealError("Could not open the folder.", details=f"{path}: {exc}") from exc


def _safe_filename(name: str) -> str:
    stem, dot, ext = Path(name).name.rpartition(".")
    stem = stem if dot else ext
    ext = ext.lower() if dot else ""
    return f"{slugify(stem, 80)}.{ext}" if ext else slugify(stem, 80)


# --- app factory ----------------------------------------------------------------------------------


def create_app(ctx: Context) -> FastAPI:  # noqa: C901 - one place that lists the whole API contract
    app = FastAPI(title="SnipScout", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.ctx = ctx

    @app.middleware("http")
    async def guard(request: Request, call_next: Callable[[Request], Any]) -> Response:
        host = request.headers.get("host", "")
        if ctx.allowed_hosts and host not in ctx.allowed_hosts:
            return JSONResponse(
                {"error": {"code": "forbidden_host", "message": "Forbidden host."}}, status_code=403
            )
        origin = request.headers.get("origin")
        if origin and origin not in {f"http://{h}" for h in ctx.allowed_hosts | {host}}:
            return JSONResponse(
                {"error": {"code": "forbidden_origin", "message": "Forbidden origin."}}, status_code=403
            )
        if request.url.path.startswith("/api/"):
            given = request.cookies.get(COOKIE) or request.headers.get(TOKEN_HEADER) or ""
            if not secrets.compare_digest(given, ctx.token):
                return JSONResponse(
                    {"error": {"code": "unauthorized", "message": "Missing session."}}, status_code=401
                )
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.exception_handler(SnipScoutError)
    async def on_error(_: Request, exc: SnipScoutError) -> JSONResponse:
        status = next(
            (s for cls, s in _STATUS.items() if isinstance(exc, cls)),
            400 if isinstance(exc, ApiError) else 500,
        )
        return JSONResponse(
            {"error": {"code": exc.code, "message": str(exc), "details": exc.details}}, status_code=status
        )

    # --- frontend ---------------------------------------------------------------------------------
    @app.get("/", include_in_schema=False)
    async def index(request: Request, t: str | None = None) -> Response:
        if t is not None:
            if not secrets.compare_digest(t, ctx.token):
                return HTMLResponse("Invalid session link.", status_code=403)
            resp = RedirectResponse("/", status_code=303)
            resp.set_cookie(COOKIE, ctx.token, httponly=True, samesite="strict", path="/")
            return resp
        if not secrets.compare_digest(request.cookies.get(COOKIE, ""), ctx.token):
            return HTMLResponse("<p>Open SnipScout from its window or launcher.</p>", status_code=403)
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    # --- system -----------------------------------------------------------------------------------
    @app.get("/api/v1/system/status")
    def system_status() -> dict[str, Any]:
        import psutil

        b = ctx.binaries
        return {
            "version": __version__,
            "offline": is_offline(),
            "ffmpeg": {
                "ok": b is not None,
                "source": b.source if b else None,
                "version": b.caps.version if b else None,
                "ffprobe": bool(b and b.ffprobe),
            },
            "hardware": {
                "os": f"{platform.system()} {platform.release()}",
                "cpu_threads": psutil.cpu_count() or 1,
                "ram_gb": round(psutil.virtual_memory().total / 1e9, 1),
            },
            "models": [
                {
                    "name": s.name,
                    "label": s.label,
                    "bytes": s.total_bytes,
                    "installed": modelstore.is_installed(s.name),
                    "rtf": measured_rtf(s.name) or s.default_rtf,
                    "measured": measured_rtf(s.name) is not None,
                }
                for s in modelstore.MODELS.values()
            ],
            "recommended_model": modelstore.DEFAULT_MODEL,
            "first_run": not any(modelstore.is_installed(n) for n in modelstore.MODELS),
            "data_dir": str(data_dir()),
            "output_dir": str(output_dir()),
            "disk_free_gb": round(
                shutil.disk_usage(data_dir() if data_dir().exists() else Path.home()).free / 1e9, 1
            ),
        }

    @app.post("/api/v1/system/models/download")
    async def download_model(body: DownloadRequest, request: Request) -> StreamingResponse:
        modelstore.get_spec(body.model)  # validates name before streaming starts
        token = CancelToken()
        q: queue.Queue[dict[str, Any] | None] = queue.Queue()

        def work() -> None:
            try:
                modelstore.download_model(
                    body.model, cancel=token, on_progress=lambda d, t: q.put({"done": d, "total": t})
                )
                q.put({"state": "done"})
            except CancelledError:
                q.put({"state": "paused"})
            except SnipScoutError as exc:
                q.put({"state": "error", "error_code": exc.code, "message": str(exc)})
            finally:
                q.put(None)

        async def stream() -> AsyncIterator[str]:
            fut = asyncio.get_running_loop().run_in_executor(None, work)
            last_pct = -1.0
            try:
                while True:
                    item = await asyncio.to_thread(q.get)
                    if item is None:
                        break
                    if "done" in item:  # throttle to ~0.5% steps
                        pct = item["done"] / max(item["total"], 1) * 100
                        if pct - last_pct < 0.5 and item["done"] < item["total"]:
                            continue
                        last_pct = pct
                    yield _sse(item, "download")
                    if await request.is_disconnected():
                        token.cancel()
            finally:
                if not fut.done():
                    token.cancel()  # client went away: pause, keep the .part files
                await fut

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store"}
        )

    # --- settings & storage ---------------------------------------------------------------------
    def _settings_json(prefs: Preferences) -> dict[str, Any]:
        return {
            **prefs.model_dump(mode="json"),
            "output_dir_resolved": str(output_dir()),
            "output_dir_default": str(default_output_dir()),
            "output_dir_locked": bool(os.environ.get("SNIPSCOUT_OUTPUT_DIR")),
        }

    @app.get("/api/v1/settings")
    def get_settings() -> dict[str, Any]:
        return _settings_json(load_preferences())

    @app.patch("/api/v1/settings")
    def patch_settings(body: SettingsUpdate) -> dict[str, Any]:
        prefs = load_preferences()
        changes = body.model_dump(exclude_unset=True)
        if "output_dir" in changes:
            raw = (changes.pop("output_dir") or "").strip()
            if raw:
                folder = Path(raw).expanduser()
                if not folder.is_absolute():
                    raise ApiError("Choose a full folder path.", details=raw)
                try:
                    folder.mkdir(parents=True, exist_ok=True)
                    probe = folder / ".snipscout-write-test"
                    probe.write_text("ok", encoding="utf-8")
                    probe.unlink()
                except OSError as exc:
                    raise ApiError(
                        "SnipScout can't write to that folder.", details=f"{folder}: {exc}"
                    ) from exc
                prefs.output_dir = str(folder)
            else:
                prefs.output_dir = None
        for key, value in changes.items():
            if value is not None:
                setattr(prefs, key, value)
        save_preferences(prefs)
        return _settings_json(prefs)

    def _size(path: Path) -> int:
        if path.is_file():
            return path.stat().st_size
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) if path.is_dir() else 0

    def _cache_items() -> list[Path]:
        """Regenerable data: thumbnails, preview frames, waveform caches, the app cache folder and
        uploads that no project uses any more. Never clips, projects or extracted audio."""
        items: list[Path] = []
        for d in ctx.store.root.iterdir() if ctx.store.root.is_dir() else []:
            if d.is_dir():
                items += [d / "thumbs", d / "preview", *d.glob("envelope_*.npy"), *d.glob("waveform_*.json")]
        used = {str(p.source.path.parent) for p in ctx.store.list()}
        if ctx.uploads_dir.is_dir():
            items += [u for u in ctx.uploads_dir.iterdir() if u.is_dir() and str(u) not in used]
        items.append(cache_dir())
        return [i for i in items if i.exists()]

    @app.get("/api/v1/system/storage")
    def storage() -> dict[str, Any]:
        cache = sum(_size(i) for i in _cache_items())
        projects = _size(ctx.store.root) + (_size(ctx.uploads_dir) if ctx.uploads_dir.is_dir() else 0)
        base = data_dir() if data_dir().exists() else Path.home()
        return {
            "models_bytes": _size(models_dir()),
            "projects_bytes": max(0, projects - cache + _size(cache_dir())),
            "cache_bytes": cache,
            "free_bytes": shutil.disk_usage(base).free,
            "data_dir": str(data_dir()),
        }

    @app.post("/api/v1/system/storage/free")
    def free_storage() -> dict[str, Any]:
        freed = 0
        for item in _cache_items():
            size = _size(item)
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)
            freed += size - _size(item)
        return {"freed_bytes": freed}

    @app.delete("/api/v1/system/models/{name}", status_code=204)
    def delete_model(name: str) -> Response:
        modelstore.get_spec(name)  # validates the name
        modelstore.remove_model(name)
        return Response(status_code=204)

    # --- projects ---------------------------------------------------------------------------------
    @app.get("/api/v1/projects")
    def list_projects() -> list[dict[str, Any]]:
        return [_project_json(ctx, p) for p in ctx.store.list()]

    @app.post("/api/v1/projects", status_code=201)
    def create_project(body: CreateProject) -> dict[str, Any]:
        media = ingest.probe(Path(body.path).expanduser(), ctx.require_ffmpeg().ffprobe)
        project = ctx.store.create(media, _apply_settings(ProjectSettings(), body.settings))
        return _project_json(ctx, project)

    @app.post("/api/v1/projects/upload", status_code=201)
    async def upload_project(request: Request, filename: str) -> dict[str, Any]:
        """Browser mode: the file is streamed in the request body (no multipart, bounded size)."""
        name = _safe_filename(filename)
        if Path(name).suffix.lower() not in ingest.SUPPORTED_EXTS:
            raise UnsupportedMediaError("Unsupported file type.", details=name)
        folder = ctx.uploads_dir / uuid.uuid4().hex[:12]
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / name
        size = 0
        try:
            with dest.open("wb") as f:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > MAX_UPLOAD_BYTES:
                        raise ApiError("File too large.", details=f"limit {MAX_UPLOAD_BYTES} bytes")
                    f.write(chunk)
            media = ingest.probe(dest, ctx.require_ffmpeg().ffprobe)
        except (SnipScoutError, OSError):
            shutil.rmtree(folder, ignore_errors=True)
            raise
        project = ctx.store.create(media)
        project.name = Path(filename).stem.strip()[:200] or project.name  # display name keeps accents
        ctx.store.save(project)
        return _project_json(ctx, project)

    @app.get("/api/v1/projects/{pid}")
    def get_project(pid: str) -> dict[str, Any]:
        return _project_json(ctx, ctx.store.load(pid))

    @app.patch("/api/v1/projects/{pid}")
    def patch_project(pid: str, body: ProjectPatch) -> dict[str, Any]:
        p = ctx.store.load(pid)
        if body.name is not None:
            p.name = body.name.strip()
        p.settings = _apply_settings(p.settings, body.settings)
        ctx.store.save(p)
        return _project_json(ctx, p)

    @app.delete("/api/v1/projects/{pid}", status_code=204)
    def delete_project(pid: str) -> Response:
        ctx.store.project_dir(pid)  # validates id
        if ctx.jobs.cancel(pid):
            ctx.jobs.wait(pid, timeout=10)
        ctx.store.delete(pid)
        return Response(status_code=204)

    @app.post("/api/v1/projects/{pid}/analyze", status_code=202)
    def analyze(pid: str, body: SettingsPatch | None = None) -> dict[str, Any]:
        p = ctx.store.load(pid)
        if body is not None:
            p.settings = _apply_settings(p.settings, body)
            ctx.store.save(p)
        if not modelstore.is_installed(p.settings.model) and ctx.model_loader is load_model:
            raise ModelDownloadError("The speech model is not downloaded yet.", details=p.settings.model)
        pipe = ctx.pipeline()
        ctx.jobs.start(pid, "analyze", lambda emit, cancel: pipe.analyze(pid, on_event=emit, cancel=cancel))
        return {"started": "analyze"}

    @app.post("/api/v1/projects/{pid}/render", status_code=202)
    def render(pid: str, body: RenderRequest | None = None) -> dict[str, Any]:
        ctx.store.load(pid)
        req = body or RenderRequest()
        out = Path(req.out_dir).expanduser() if req.out_dir else None
        pipe = ctx.pipeline()
        ctx.jobs.start(
            pid,
            "render",
            lambda emit, cancel: pipe.render(
                pid,
                out_dir=out,
                clip_ids=req.clip_ids,
                on_event=emit,
                cancel=cancel,
                hardware=req.hardware,
                loudnorm=req.loudnorm,
            ),
        )
        return {"started": "render"}

    @app.post("/api/v1/projects/{pid}/cancel")
    def cancel(pid: str) -> dict[str, Any]:
        ctx.store.project_dir(pid)
        return {"cancelled": ctx.jobs.cancel(pid)}

    @app.get("/api/v1/projects/{pid}/events")
    async def events(pid: str, request: Request) -> StreamingResponse:
        ctx.store.project_dir(pid)
        q = ctx.jobs.subscribe(pid)

        async def stream() -> AsyncIterator[str]:
            try:
                yield "retry: 2000\n\n"
                while not await request.is_disconnected():
                    try:
                        event = await asyncio.to_thread(q.get, True, SSE_KEEPALIVE_S)
                    except queue.Empty:
                        yield ": keep-alive\n\n"
                        continue
                    if event is None:
                        break
                    yield _sse(event)
            finally:
                ctx.jobs.unsubscribe(pid, q)

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store"}
        )

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
        from snipscout.core.render import render_still
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
        out = render_still(
            ctx.require_ffmpeg().ffmpeg, p.source, body.at, work, work / f"frame_{tag}.jpg", ass_name, opts
        )
        (work / ass_name).unlink(missing_ok=True)
        return FileResponse(out, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    # --- media ------------------------------------------------------------------------------------
    @app.get("/api/v1/projects/{pid}/media")
    def media(pid: str) -> FileResponse:
        p = ctx.store.load(pid)
        if not p.source.path.is_file():
            raise UnsupportedMediaError("The original file is no longer there.", details=str(p.source.path))
        return FileResponse(p.source.path)  # Starlette answers Range requests with 206

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

    # --- export -----------------------------------------------------------------------------------
    def _export_dir(pid: str) -> Path:
        p = ctx.store.load(pid)
        folder = p.export_dir or ctx.store.project_dir(pid) / "exports"
        if not folder.is_dir():
            raise ApiError("Nothing exported yet.", details=str(folder))
        return folder

    @app.get("/api/v1/projects/{pid}/export.zip")
    def export_zip(pid: str) -> StreamingResponse:
        folder = _export_dir(pid)
        files = sorted(f for f in folder.iterdir() if f.is_file())
        tmp = tempfile.SpooledTemporaryFile(max_size=64 * 1024**2)  # noqa: SIM115 - closed by the generator
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_STORED) as z:  # MP4s are already compressed
            for f in files:
                z.write(f, arcname=f.name)
        tmp.seek(0)

        def chunks() -> Iterator[bytes]:
            try:
                while block := tmp.read(1024 * 1024):
                    yield block
            finally:
                tmp.close()

        name = slugify(ctx.store.load(pid).name, 60) + "-snipscout.zip"
        return StreamingResponse(
            chunks(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    @app.get("/api/v1/projects/{pid}/exports")
    def list_exports(pid: str) -> dict[str, Any]:
        """Exported clips of the last render (from metadata.json) with their caption text."""
        folder = _export_dir(pid)
        meta_file = folder / "metadata.json"
        if not meta_file.is_file():
            raise ApiError("Nothing exported yet.", details=str(folder))
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        captions = (
            (folder / "captions.txt").read_text(encoding="utf-8")
            if (folder / "captions.txt").is_file()
            else ""
        )
        blocks = {
            b.split(" ===\n", 1)[0].strip("= \n"): b.split(" ===\n", 1)[1].strip()
            for b in captions.split("=== ")[1:]
            if " ===\n" in b
        }
        files = []
        for c in meta["clips"]:
            video = folder / c["file"]
            files.append(
                {
                    **c,
                    "exists": video.is_file(),
                    "size_bytes": video.stat().st_size if video.is_file() else 0,
                    "caption": blocks.get(c["file"], c["title"]),
                }
            )
        return {"folder": str(folder), "clips": files}

    @app.get("/api/v1/projects/{pid}/exports/{name}")
    def export_file(pid: str, name: str, download: bool = False) -> FileResponse:
        """One exported file. Only names present in the export folder are served (no traversal)."""
        folder = _export_dir(pid)
        allowed = {
            f.name: f
            for f in folder.iterdir()
            if f.is_file() and f.suffix.lower() in {".mp4", ".srt", ".vtt", ".txt", ".json"}
        }
        if name not in allowed:
            raise ProjectNotFoundError("Unknown file.", details=name)
        disposition = "attachment" if download else "inline"
        return FileResponse(allowed[name], filename=name, content_disposition_type=disposition)

    @app.post("/api/v1/projects/{pid}/reveal", status_code=204)
    def reveal(pid: str) -> Response:
        _reveal(_export_dir(pid))
        return Response(status_code=204)

    return app
