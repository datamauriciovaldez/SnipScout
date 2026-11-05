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
from snipscout.config import data_dir, is_offline
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
from snipscout.core.procs import CancelToken, run_ffmpeg
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
    hardware: bool = False
    loudnorm: bool = False


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
    out["estimate_s"] = round(
        estimate_seconds(
            min(p.source.duration, 600) if p.settings.quick_analysis else p.source.duration, p.settings.model
        )
    )
    return out


def _sse(event: JobEvent | dict[str, Any], name: str = "progress") -> str:
    data = event.model_dump_json() if isinstance(event, JobEvent) else json.dumps(event, ensure_ascii=False)
    return f"event: {name}\ndata: {data}\n\n"


def _reveal(path: Path) -> None:
    """Open a folder in the OS file manager (argument list, never a shell)."""
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]  # noqa: S606 - opens a folder the app created
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])  # noqa: S607
    else:
        subprocess.Popen(["xdg-open", str(path)])  # noqa: S607


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
        return _project_json(ctx, ctx.store.create(media))

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
                pid, out_dir=out, on_event=emit, cancel=cancel, hardware=req.hardware, loudnorm=req.loudnorm
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
        ctx.store.load(pid)
        clips = ctx.store.load_clips(pid) or ClipSet()
        return clips.model_dump(mode="json")

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

    @app.post("/api/v1/projects/{pid}/clips/{cid}/preview-frame", status_code=501)
    def preview_frame(pid: str, cid: str) -> dict[str, Any]:
        ctx.store.project_dir(pid)
        return {"error": {"code": "not_available", "message": "Real-frame preview arrives in v0.2."}}

    # --- media ------------------------------------------------------------------------------------
    @app.get("/api/v1/projects/{pid}/media")
    def media(pid: str) -> FileResponse:
        p = ctx.store.load(pid)
        if not p.source.path.is_file():
            raise UnsupportedMediaError("The original file is no longer there.", details=str(p.source.path))
        return FileResponse(p.source.path)  # Starlette answers Range requests with 206

    @app.get("/api/v1/projects/{pid}/waveform")
    def waveform(pid: str, points: int = 800) -> dict[str, Any]:
        ctx.store.load(pid)
        points = max(50, min(points, 4000))
        wav = ctx.store.audio_path(pid)
        if not wav.exists():
            raise ApiError("Analyze the video first.", details="no audio extracted yet")
        cache = ctx.store.project_dir(pid) / f"waveform_{points}.json"
        if cache.exists():
            return dict(json.loads(cache.read_text(encoding="utf-8")))
        env = audio.rms_envelope_file(wav)
        import numpy as np

        if len(env) == 0:
            peaks: list[float] = []
        else:
            buckets = np.array_split(env, min(points, len(env)))
            raw = np.array([float(np.max(b)) for b in buckets])
            top = float(np.percentile(raw, 99)) or 1.0
            peaks = [round(min(1.0, v / top), 3) for v in raw]
        data = {"duration": audio.wav_duration(wav), "points": len(peaks), "peaks": peaks}
        cache.write_text(json.dumps(data), encoding="utf-8")
        return data

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

    @app.post("/api/v1/projects/{pid}/reveal", status_code=204)
    def reveal(pid: str) -> Response:
        _reveal(_export_dir(pid))
        return Response(status_code=204)

    return app
