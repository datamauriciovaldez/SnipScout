"""System report used by ``snipscout doctor`` and, later, the first-run hardware check."""

from __future__ import annotations

import platform
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

import psutil

from snipscout import __version__
from snipscout.config import data_dir, is_offline
from snipscout.core.binaries import resolve_ffmpeg
from snipscout.core.errors import FfmpegMissingError


@dataclass
class SystemReport:
    snipscout: str
    python: str
    os: str
    cpu_cores_logical: int
    cpu_cores_physical: int | None
    ram_gb: float
    nvidia_gpu_tool: bool
    data_dir: str
    disk_free_gb: float | None
    offline: bool
    ffmpeg_ok: bool
    ffmpeg: dict[str, str | bool | None] = field(default_factory=dict)
    ffmpeg_error: str | None = None

    @property
    def ok(self) -> bool:
        return self.ffmpeg_ok


def _disk_free_gb(path: Path) -> float | None:
    probe = path
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        return round(shutil.disk_usage(probe).free / 1e9, 1)
    except OSError:
        return None


def collect(*, use_cache: bool = True) -> SystemReport:
    ddir = data_dir()
    report = SystemReport(
        snipscout=__version__,
        python=sys.version.split()[0],
        os=f"{platform.system()} {platform.release()} ({platform.machine()})",
        cpu_cores_logical=psutil.cpu_count(logical=True) or 1,
        cpu_cores_physical=psutil.cpu_count(logical=False),
        ram_gb=round(psutil.virtual_memory().total / 1e9, 1),
        # Presence of the NVIDIA tool only hints at a GPU; SnipScout never requires one.
        nvidia_gpu_tool=shutil.which("nvidia-smi") is not None,
        data_dir=str(ddir),
        disk_free_gb=_disk_free_gb(ddir),
        offline=is_offline(),
        ffmpeg_ok=False,
    )
    try:
        found = resolve_ffmpeg(use_cache=use_cache)
    except FfmpegMissingError as exc:
        report.ffmpeg_error = f"{exc}\n{exc.details or ''}".strip()
        return report
    report.ffmpeg_ok = True
    report.ffmpeg = {
        "path": str(found.ffmpeg),
        "source": found.source,
        "version": found.caps.version,
        "ffprobe": str(found.ffprobe) if found.ffprobe else None,
    }
    return report
