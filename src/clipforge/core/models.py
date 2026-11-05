"""Data models shared by the pipeline, storage and the API. Everything here is JSON-serialisable."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


# --- Media -----------------------------------------------------------------------------------------


class AudioTrack(_Model):
    index: int  # 0-based index among audio streams (ffmpeg "-map 0:a:<index>")
    codec: str | None = None
    channels: int | None = None
    sample_rate: int | None = None
    language: str | None = None


class MediaInfo(_Model):
    path: Path
    size_bytes: int
    container: str
    duration: float
    has_video: bool
    video_codec: str | None = None
    width: int | None = None  # coded size, before rotation
    height: int | None = None
    fps: float | None = None
    variable_frame_rate: bool = False
    rotation: int = 0  # 0/90/180/270, as reported by the display matrix
    audio_tracks: list[AudioTrack] = Field(default_factory=list)

    @property
    def display_size(self) -> tuple[int, int] | None:
        """Size as the viewer sees it (after rotation)."""
        if self.width is None or self.height is None:
            return None
        if self.rotation in (90, 270):
            return self.height, self.width
        return self.width, self.height


# --- Transcript ------------------------------------------------------------------------------------


class Word(_Model):
    text: str
    start: float
    end: float
    prob: float = 1.0


class Transcript(_Model):
    language: str | None = None
    model: str | None = None
    duration: float = 0.0  # media duration
    processed_until: float = 0.0  # seconds transcribed so far (for resume)
    complete: bool = False
    words: list[Word] = Field(default_factory=list)


# --- Settings & project ----------------------------------------------------------------------------


class ClipLength(StrEnum):
    SHORT = "short"  # 15-30 s
    MEDIUM = "medium"  # 30-60 s
    LONG = "long"  # 60-90 s

    @property
    def bounds(self) -> tuple[float, float]:
        return {"short": (15.0, 30.0), "medium": (30.0, 60.0), "long": (60.0, 90.0)}[self.value]


class AspectRatio(StrEnum):
    VERTICAL = "9:16"
    SQUARE = "1:1"
    HORIZONTAL = "16:9"
    ORIGINAL = "original"


class ProjectSettings(_Model):
    clip_length: ClipLength = ClipLength.SHORT
    aspect: AspectRatio = AspectRatio.VERTICAL
    subtitle_style: str = "bold-pop"
    language: str | None = None  # None = auto-detect
    model: str = "base"
    audio_track: int = 0
    quick_analysis: bool = False  # only the first ~10 minutes


class ProjectStatus(StrEnum):
    NEW = "new"
    ANALYZING = "analyzing"
    ANALYZED = "analyzed"
    RENDERING = "rendering"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


def _now() -> datetime:
    return datetime.now(UTC)


class Project(_Model):
    id: str
    name: str
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    source: MediaInfo
    settings: ProjectSettings = Field(default_factory=ProjectSettings)
    status: ProjectStatus = ProjectStatus.NEW
    error_code: str | None = None


# --- Progress events -------------------------------------------------------------------------------


class JobState(StrEnum):
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


class JobEvent(_Model):
    """Progress event emitted by the core. ``message`` is an i18n key; ``params`` fill its placeholders."""

    stage: str
    progress: float = 0.0  # 0..1 within the stage
    message: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    state: JobState = JobState.RUNNING
    error_code: str | None = None
