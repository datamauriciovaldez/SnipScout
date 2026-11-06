"""User preferences stored in ``<data>/preferences.json`` (output folder, export quality, ...)."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from snipscout.config import data_dir
from snipscout.core.storage import atomic_write_text


class Quality(StrEnum):
    LIGHT = "light"  # smaller files
    STANDARD = "standard"
    HIGH = "high"

    @property
    def crf(self) -> int:
        return {"light": 24, "standard": 20, "high": 17}[self.value]


class Preferences(BaseModel):
    model_config = ConfigDict(extra="ignore")

    output_dir: str | None = None  # None = Downloads/SnipScout
    quality: Quality = Quality.STANDARD
    hardware: bool = False  # try a hardware H.264 encoder first (falls back to libx264)
    loudnorm: bool = False  # normalise loudness to -14 LUFS
    ollama_model: str | None = None  # model used by "Improve with local AI" (None = first installed)


def preferences_file() -> Path:
    return data_dir() / "preferences.json"


def load_preferences() -> Preferences:
    try:
        return Preferences.model_validate_json(preferences_file().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Preferences()
    except (OSError, ValidationError, ValueError):
        return Preferences()  # a broken file must never stop the app; it is rewritten on next save


def save_preferences(prefs: Preferences) -> None:
    """Raises ``StorageError`` when the file can't be written."""
    atomic_write_text(preferences_file(), prefs.model_dump_json(indent=1))
