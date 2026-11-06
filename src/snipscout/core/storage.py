"""Project storage on disk. One folder per project:

    <data>/projects/<id>/project.json, transcript.json, clips.json, audio.wav, exports/ ...

Writes are atomic (temp file + ``os.replace``) so a crash never leaves a half-written JSON.
On Windows a file that another thread is reading or replacing at that very moment raises a
transient ``PermissionError`` (sharing violation); reads and replaces retry briefly in that case.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
import unicodedata
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from snipscout.config import data_dir
from snipscout.core.errors import SnipScoutError
from snipscout.core.models import ClipSet, MediaInfo, Project, ProjectSettings, Transcript

M = TypeVar("M", bound=BaseModel)
T = TypeVar("T")
SHARING_RETRIES = 8  # ~0.7 s in total
_ID_RE = re.compile(r"^[a-f0-9]{12}$")


class ProjectNotFoundError(SnipScoutError):
    code = "project_not_found"


class StorageError(SnipScoutError):
    code = "storage"


def retry_sharing(op: Callable[[], T]) -> T:
    """Run ``op``, retrying a few times on ``PermissionError`` (Windows sharing violations are transient)."""
    for attempt in range(SHARING_RETRIES):
        try:
            return op()
        except PermissionError:
            if attempt == SHARING_RETRIES - 1:
                raise
            time.sleep(0.02 * (attempt + 1))
    raise AssertionError("unreachable")  # pragma: no cover


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        Path(tmp).chmod(0o644)  # mkstemp creates 0600; exported files must be readable like normal files
        retry_sharing(lambda: Path(tmp).replace(path))
    except OSError as exc:
        Path(tmp).unlink(missing_ok=True)
        raise StorageError(
            "Could not write project data (disk full or no permission?).", details=str(exc)
        ) from exc


def slugify(text: str, max_len: int = 40) -> str:
    """ASCII, filesystem-safe slug. Never empty."""
    norm = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", norm).strip("-").lower()[:max_len].strip("-")
    return slug or "clip"


class ProjectStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or (data_dir() / "projects")

    # -- paths -------------------------------------------------------------------------------------
    def project_dir(self, project_id: str) -> Path:
        """Validated folder of a project. Rejects anything that is not a well-formed id (path traversal)."""
        if not _ID_RE.fullmatch(project_id):
            raise ProjectNotFoundError("Unknown project.", details=f"invalid id {project_id!r}")
        return self.root / project_id

    def _file(self, project_id: str, name: str) -> Path:
        return self.project_dir(project_id) / name

    # -- generic JSON ------------------------------------------------------------------------------
    def _save(self, project_id: str, name: str, model: BaseModel) -> None:
        atomic_write_text(self._file(project_id, name), model.model_dump_json(indent=1))

    def _load(self, project_id: str, name: str, cls: type[M]) -> M | None:
        path = self._file(project_id, name)
        try:
            return cls.model_validate_json(retry_sharing(lambda: path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            return None
        except (OSError, ValidationError, ValueError) as exc:
            raise StorageError(f"Corrupted file {name}.", details=f"{path}: {exc}") from exc

    # -- projects ----------------------------------------------------------------------------------
    def create(self, source: MediaInfo, settings: ProjectSettings | None = None) -> Project:
        project = Project(
            id=uuid.uuid4().hex[:12],
            name=source.path.stem,
            source=source,
            settings=settings or ProjectSettings(),
        )
        self.project_dir(project.id).mkdir(parents=True, exist_ok=False)
        self.save(project)
        return project

    def save(self, project: Project) -> None:
        project.updated_at = datetime.now(UTC)
        self._save(project.id, "project.json", project)

    def load(self, project_id: str) -> Project:
        project = self._load(project_id, "project.json", Project)
        if project is None:
            raise ProjectNotFoundError("Unknown project.", details=project_id)
        return project

    def list(self) -> list[Project]:
        if not self.root.is_dir():
            return []
        out = []
        for d in self.root.iterdir():
            if d.is_dir() and _ID_RE.fullmatch(d.name) and (d / "project.json").is_file():
                try:
                    out.append(self.load(d.name))
                except StorageError:
                    continue  # skip corrupted projects in listings; opening one shows the error
        return sorted(out, key=lambda p: p.updated_at, reverse=True)

    def delete(self, project_id: str) -> None:
        d = self.project_dir(project_id)
        if not d.is_dir():
            raise ProjectNotFoundError("Unknown project.", details=project_id)
        shutil.rmtree(d)

    # -- artefacts ---------------------------------------------------------------------------------
    def audio_path(self, project_id: str) -> Path:
        return self._file(project_id, "audio.wav")

    def save_transcript(self, project_id: str, transcript: Transcript) -> None:
        self._save(project_id, "transcript.json", transcript)

    def load_transcript(self, project_id: str) -> Transcript | None:
        return self._load(project_id, "transcript.json", Transcript)

    def save_clips(self, project_id: str, clips: ClipSet) -> None:
        self._save(project_id, "clips.json", clips)

    def load_clips(self, project_id: str) -> ClipSet | None:
        return self._load(project_id, "clips.json", ClipSet)
