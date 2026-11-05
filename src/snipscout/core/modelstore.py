"""Whisper model catalogue and downloads.

Downloads use plain HTTPS against public Hugging Face "resolve" URLs (no account, no token),
pinned to a commit, with byte progress, pause/resume (HTTP Range on ``*.part`` files),
cooperative cancellation and SHA-256 verification of the weights.
"""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from snipscout.config import models_dir
from snipscout.core.errors import CancelledError, ModelDownloadError
from snipscout.core.net import require_network
from snipscout.core.procs import CancelToken

HF_BASE = "https://huggingface.co"
FILES = ("config.json", "tokenizer.json", "vocabulary.txt", "model.bin")
CHUNK = 1 << 20


@dataclass(frozen=True)
class WhisperSpec:
    name: str
    label: str  # i18n key suffix: models.<label>
    repo: str
    revision: str
    model_sha256: str
    total_bytes: int
    default_rtf: float  # transcribe_seconds / audio_seconds, measured in H0 on a 4-vCPU Xeon, int8 CPU


# Revisions and checksums read from the Hugging Face API on 2026-11-05 (docs/spike-report.md).
MODELS: dict[str, WhisperSpec] = {
    "tiny": WhisperSpec(
        "tiny",
        "fast",
        "Systran/faster-whisper-tiny",
        "d90ca5fe260221311c53c58e660288d3deb8d356",
        "dcb76c6586fc06cbdac6dd21f14cfd129cc4cdd9dce19bf4ffa62e59cbe6e6d1",
        78_203_619,
        0.14,
    ),
    "base": WhisperSpec(
        "base",
        "balanced",
        "Systran/faster-whisper-base",
        "ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66",
        "d01c3014881c9c6f3133c182f3d2887eb6ca1c789a7538c5c007196857a0a6a9",
        147_882_941,
        0.18,
    ),
    "small": WhisperSpec(
        "small",
        "accurate",
        "Systran/faster-whisper-small",
        "536b0662742c02347bc0e980a01041f333bce120",
        "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671",
        486_212_372,
        0.38,
    ),
}
DEFAULT_MODEL = "base"


def get_spec(name: str) -> WhisperSpec:
    try:
        return MODELS[name]
    except KeyError:
        raise ModelDownloadError(
            "Unknown model.", details=f"{name!r}; choose one of {sorted(MODELS)}"
        ) from None


def model_dir(name: str) -> Path:
    return models_dir() / "whisper" / get_spec(name).name


def _marker(name: str) -> Path:
    return model_dir(name) / ".verified"


def is_installed(name: str) -> bool:
    d = model_dir(name)
    return _marker(name).is_file() and all((d / f).is_file() for f in FILES)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(CHUNK):
            h.update(block)
    return h.hexdigest()


def _url(spec: WhisperSpec, filename: str) -> str:
    return f"{HF_BASE}/{spec.repo}/resolve/{spec.revision}/{filename}"


def _download_file(
    client: httpx.Client, url: str, dest: Path, on_bytes: Callable[[int], None], cancel: CancelToken | None
) -> None:
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={have}-"} if have else {}
    with client.stream("GET", url, headers=headers) as r:
        if r.status_code == 416:  # already complete
            part.replace(dest)
            return
        if r.status_code == 200 and have:  # server ignored Range: restart
            have = 0
            part.unlink(missing_ok=True)
        if r.status_code not in (200, 206):
            raise ModelDownloadError("Model download failed.", details=f"HTTP {r.status_code} for {url}")
        if have:
            on_bytes(have)
        with part.open("ab") as f:
            for chunk in r.iter_bytes(CHUNK):
                if cancel is not None and cancel.cancelled:
                    raise CancelledError("Download paused.")
                f.write(chunk)
                on_bytes(len(chunk))
    part.replace(dest)


def download_model(
    name: str,
    *,
    on_progress: Callable[[int, int], None] | None = None,
    cancel: CancelToken | None = None,
    client: httpx.Client | None = None,
) -> Path:
    """Download (or resume) model ``name``. Calls ``on_progress(done_bytes, total_bytes)``.

    Cancelling keeps the ``.part`` files, so calling again resumes ("pause/resume").
    """
    spec = get_spec(name)
    d = model_dir(name)
    if is_installed(name):
        return d
    require_network(f"download the {name} speech model")
    d.mkdir(parents=True, exist_ok=True)
    done = 0

    def bump(n: int) -> None:
        nonlocal done
        done += n
        if on_progress:
            on_progress(min(done, spec.total_bytes), spec.total_bytes)

    own = client is None
    http = client or httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30.0, read=60.0))
    try:
        for filename in FILES:
            dest = d / filename
            if dest.is_file():
                bump(dest.stat().st_size)
                continue
            _download_file(http, _url(spec, filename), dest, bump, cancel)
    except httpx.HTTPError as exc:
        raise ModelDownloadError(
            "Model download failed. Check your internet connection.", details=str(exc)
        ) from exc
    except OSError as exc:
        raise ModelDownloadError("Could not save the model (disk full?).", details=str(exc)) from exc
    finally:
        if own:
            http.close()
    if _sha256(d / "model.bin") != spec.model_sha256:
        (d / "model.bin").unlink(missing_ok=True)
        raise ModelDownloadError(
            "The downloaded model is corrupted; please try again.", details=f"{name}: sha256 mismatch"
        )
    _marker(name).write_text(spec.revision, encoding="utf-8")
    return d


def remove_model(name: str) -> None:
    shutil.rmtree(model_dir(name), ignore_errors=True)
