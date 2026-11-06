"""System status, speech models, settings, storage and the optional local AI status."""

from __future__ import annotations

import asyncio
import os
import platform
import queue
import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import (
    Response,
    StreamingResponse,
)

from snipscout import __version__
from snipscout.config import cache_dir, data_dir, default_output_dir, is_offline, models_dir, output_dir
from snipscout.core import modelstore
from snipscout.core.errors import (
    CancelledError,
    SnipScoutError,
)
from snipscout.core.preferences import Preferences, load_preferences, save_preferences
from snipscout.core.procs import CancelToken
from snipscout.core.transcribe import measured_rtf
from snipscout.web.common import ApiError, Context, DownloadRequest, SettingsUpdate, sse_event


def register(app: FastAPI, ctx: Context) -> None:  # noqa: C901 - routes as closures over ctx
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
                    yield sse_event(item, "download")
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
        if "ollama_model" in changes:
            prefs.ollama_model = (changes.pop("ollama_model") or "").strip()[:200] or None
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

    @app.get("/api/v1/system/ollama")
    def ollama_status() -> dict[str, Any]:
        """Is a local Ollama server running, and which models does it have? Never downloads anything."""
        client = ctx.ollama_factory()
        try:
            st = client.status()
        finally:
            client.close()
        pref = load_preferences().ollama_model
        model = pref if pref in st.models else (st.models[0] if st.models else None)
        return {**st.model_dump(), "model": model, "preferred": pref}
