"""Exported files: listing, single files, ZIP and showing the folder."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import (
    FileResponse,
    Response,
    StreamingResponse,
)

from snipscout.core.errors import (
    SnipScoutError,
)
from snipscout.core.storage import ProjectNotFoundError, slugify
from snipscout.web.common import ApiError, Context


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


def register(app: FastAPI, ctx: Context) -> None:  # noqa: C901 - routes as closures over ctx
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
