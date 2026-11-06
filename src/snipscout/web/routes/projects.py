"""Projects: create/upload, read/update/delete, analyze, render, improve, cancel and progress events."""

from __future__ import annotations

import asyncio
import queue
import shutil
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import (
    Response,
    StreamingResponse,
)

from snipscout.core import ingest, modelstore
from snipscout.core.errors import (
    ModelDownloadError,
    OllamaUnavailableError,
    SnipScoutError,
    UnsupportedMediaError,
)
from snipscout.core.models import (
    JobEvent,
    ProjectSettings,
)
from snipscout.core.preferences import load_preferences
from snipscout.core.procs import CancelToken
from snipscout.core.storage import slugify
from snipscout.core.transcribe import load_model
from snipscout.web.common import (
    MAX_UPLOAD_BYTES,
    SSE_KEEPALIVE_S,
    ApiError,
    Context,
    CreateProject,
    ImproveRequest,
    ProjectPatch,
    RenderRequest,
    SettingsPatch,
    apply_settings,
    project_json,
    sse_event,
)


def _safe_filename(name: str) -> str:
    stem, dot, ext = Path(name).name.rpartition(".")
    stem = stem if dot else ext
    ext = ext.lower() if dot else ""
    return f"{slugify(stem, 80)}.{ext}" if ext else slugify(stem, 80)


# --- app factory ----------------------------------------------------------------------------------


def register(app: FastAPI, ctx: Context) -> None:  # noqa: C901 - routes as closures over ctx
    # --- projects ---------------------------------------------------------------------------------
    @app.get("/api/v1/projects")
    def list_projects() -> list[dict[str, Any]]:
        return [project_json(ctx, p) for p in ctx.store.list()]

    @app.post("/api/v1/projects", status_code=201)
    def create_project(body: CreateProject) -> dict[str, Any]:
        media = ingest.probe(Path(body.path).expanduser(), ctx.require_ffmpeg().ffprobe)
        project = ctx.store.create(media, apply_settings(ProjectSettings(), body.settings))
        return project_json(ctx, project)

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
        return project_json(ctx, project)

    @app.get("/api/v1/projects/{pid}")
    def get_project(pid: str) -> dict[str, Any]:
        return project_json(ctx, ctx.store.load(pid))

    @app.patch("/api/v1/projects/{pid}")
    def patch_project(pid: str, body: ProjectPatch) -> dict[str, Any]:
        p = ctx.store.load(pid)
        if body.name is not None:
            p.name = body.name.strip()
        p.settings = apply_settings(p.settings, body.settings)
        ctx.store.save(p)
        return project_json(ctx, p)

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
            p.settings = apply_settings(p.settings, body)
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

    @app.post("/api/v1/projects/{pid}/improve", status_code=202)
    def improve(pid: str, body: ImproveRequest | None = None) -> dict[str, Any]:
        ctx.store.load(pid)
        if not ctx.store.load_clips(pid):
            raise ApiError("Analyze the video first.")
        client = ctx.ollama_factory()
        try:
            st = client.status()
        finally:
            client.close()
        if not st.available:
            raise OllamaUnavailableError("No local Ollama server is running.", details=st.url)
        wanted = (body.model if body else None) or load_preferences().ollama_model
        model = wanted if wanted in st.models else (st.models[0] if st.models and not wanted else None)
        if model is None:
            raise OllamaUnavailableError("This model is not installed in Ollama.", details=wanted or "")
        pipe = ctx.pipeline()

        def work(emit: Callable[[JobEvent], None], cancel: CancelToken) -> object:
            client = ctx.ollama_factory()
            try:
                return pipe.improve(pid, model, client=client, on_event=emit, cancel=cancel)
            finally:
                client.close()

        ctx.jobs.start(pid, "improve", work)
        return {"started": "improve", "model": model}

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
                    yield sse_event(event)
            finally:
                ctx.jobs.unsubscribe(pid, q)

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store"}
        )
