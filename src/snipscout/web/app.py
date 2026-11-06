"""Local HTTP API (/api/v1) + static frontend.

Security model (spec 5.6): bound to 127.0.0.1 on a random free port; a per-launch session token is
handed to the window once (``/?t=TOKEN``) and kept in an HttpOnly, SameSite=Strict cookie. Every
/api request needs that cookie (or the ``X-SnipScout-Token`` header). Host and Origin headers are
checked to block DNS-rebinding and cross-site requests. No CORS.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles

from snipscout import __version__
from snipscout.core.errors import (
    CancelledError,
    FfmpegMissingError,
    ModelDownloadError,
    NoSpeechError,
    OfflineError,
    OllamaFailedError,
    OllamaUnavailableError,
    SnipScoutError,
    UnsupportedMediaError,
)
from snipscout.core.storage import ProjectNotFoundError
from snipscout.web.common import COOKIE, STATIC, TOKEN_HEADER, ApiError, Context
from snipscout.web.jobs import JobBusyError
from snipscout.web.routes import clips, exports, projects, system

__all__ = ["COOKIE", "Context", "create_app"]  # Context/COOKIE re-exported for callers and tests

_STATUS = {
    ProjectNotFoundError: 404,
    UnsupportedMediaError: 400,
    NoSpeechError: 422,
    JobBusyError: 409,
    CancelledError: 409,
    OfflineError: 503,
    FfmpegMissingError: 503,
    ModelDownloadError: 502,
    OllamaUnavailableError: 503,
    OllamaFailedError: 502,
}


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

    for routes in (system, projects, clips, exports):
        routes.register(app, ctx)
    return app
