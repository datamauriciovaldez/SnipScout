"""App-wide paths and environment flags."""

import json
import os
from pathlib import Path

from platformdirs import PlatformDirs

APP_NAME = "SnipScout"
_dirs = PlatformDirs(APP_NAME, appauthor=False)


def _env_path(var: str, default: Path) -> Path:
    value = os.environ.get(var)
    return Path(value) if value else default


def cache_dir() -> Path:
    """Disposable data (capability probes, thumbnails). Override with ``SNIPSCOUT_CACHE_DIR``."""
    return _env_path("SNIPSCOUT_CACHE_DIR", Path(_dirs.user_cache_dir))


def data_dir() -> Path:
    """Persistent data (models, projects). Override with ``SNIPSCOUT_DATA_DIR``."""
    return _env_path("SNIPSCOUT_DATA_DIR", Path(_dirs.user_data_dir))


def default_output_dir() -> Path:
    downloads = _dirs.user_downloads_dir or str(Path.home() / "Downloads")
    return Path(downloads) / APP_NAME


def output_dir() -> Path:
    """Exported clips go to ``SNIPSCOUT_OUTPUT_DIR``, else the user's preference, else Downloads/SnipScout."""
    env = os.environ.get("SNIPSCOUT_OUTPUT_DIR")
    if env:
        return Path(env)
    try:  # read the preference without importing the core (config stays dependency-free)
        chosen = json.loads((data_dir() / "preferences.json").read_text(encoding="utf-8")).get("output_dir")
    except (OSError, ValueError, AttributeError):
        chosen = None
    return Path(chosen) if chosen else default_output_dir()


def models_dir() -> Path:
    return data_dir() / "models"


def is_offline() -> bool:
    """True when ``SNIPSCOUT_OFFLINE`` is set to a truthy value."""
    return os.environ.get("SNIPSCOUT_OFFLINE", "").strip().lower() in {"1", "true", "yes", "on"}
