"""App-wide paths and environment flags."""

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


def output_dir() -> Path:
    """Where exported clips go by default. Override with ``SNIPSCOUT_OUTPUT_DIR``."""
    downloads = _dirs.user_downloads_dir or str(Path.home() / "Downloads")
    return _env_path("SNIPSCOUT_OUTPUT_DIR", Path(downloads) / APP_NAME)


def models_dir() -> Path:
    return data_dir() / "models"


def is_offline() -> bool:
    """True when ``SNIPSCOUT_OFFLINE`` is set to a truthy value."""
    return os.environ.get("SNIPSCOUT_OFFLINE", "").strip().lower() in {"1", "true", "yes", "on"}
