"""Shared pieces of the local API: context, request models, constants and small helpers."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from snipscout.config import data_dir
from snipscout.core import modelstore
from snipscout.core.binaries import FfmpegBinaries
from snipscout.core.errors import (
    FfmpegMissingError,
    SnipScoutError,
)
from snipscout.core.models import (
    AspectRatio,
    ClipLength,
    Framing,
    JobEvent,
    Project,
    ProjectSettings,
)
from snipscout.core.pipeline import Pipeline
from snipscout.core.preferences import Quality
from snipscout.core.scoring.ollama import OllamaClient
from snipscout.core.storage import ProjectStore
from snipscout.core.transcribe import SpeechModel, estimate_seconds, load_model
from snipscout.web.jobs import JobManager

STATIC = Path(__file__).parent / "static"
COOKIE = "snipscout_session"
TOKEN_HEADER = "x-snipscout-token"  # noqa: S105 - header name, not a secret
MAX_UPLOAD_BYTES = 20 * 1024**3  # 20 GB
SSE_KEEPALIVE_S = 15.0


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
        ollama_factory: Callable[[], OllamaClient] = OllamaClient,
    ) -> None:
        self.store = store
        self.binaries = binaries
        self.token = token
        self.jobs = JobManager()
        self.model_loader = model_loader
        self.uploads_dir = uploads_dir or (data_dir() / "uploads")
        self.ollama_factory = ollama_factory
        self.proxies: dict[
            str, dict[str, Any]
        ] = {}  # project id -> playback proxy state (see routes/clips.py)
        self.proxies_lock = threading.Lock()
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
    follow_face: bool | None = None


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
    framing: Framing | None = None
    focus_x: float | None = Field(default=None, ge=0, le=1)


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
    framing: Framing | None = None
    focus_x: float | None = Field(default=None, ge=0, le=1)


class SettingsUpdate(BaseModel):
    output_dir: str | None = None  # "" resets to the default folder
    quality: Quality | None = None
    hardware: bool | None = None
    loudnorm: bool | None = None
    ollama_model: str | None = None  # "" = automatic


class ImproveRequest(BaseModel):
    model: str | None = Field(default=None, max_length=200)


class DownloadRequest(BaseModel):
    model: str = modelstore.DEFAULT_MODEL


# --- helpers --------------------------------------------------------------------------------------


def apply_settings(current: ProjectSettings, patch: SettingsPatch | None) -> ProjectSettings:
    if patch is None:
        return current
    data = current.model_dump()
    data.update({k: v for k, v in patch.model_dump(exclude_unset=True).items()})
    if data.get("model") not in modelstore.MODELS:
        raise ApiError("Unknown model.", details=str(data.get("model")))
    return ProjectSettings.model_validate(data)


def project_json(ctx: Context, p: Project) -> dict[str, Any]:
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


def sse_event(event: JobEvent | dict[str, Any], name: str = "progress") -> str:
    data = event.model_dump_json() if isinstance(event, JobEvent) else json.dumps(event, ensure_ascii=False)
    return f"event: {name}\ndata: {data}\n\n"
