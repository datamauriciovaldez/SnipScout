"""Subprocess helpers: cooperative cancellation and ffmpeg progress parsing."""

from __future__ import annotations

import subprocess
import threading
from collections.abc import Callable, Sequence
from pathlib import Path

from clipforge.core.errors import CancelledError, FfmpegFailedError


class CancelToken:
    """Shared flag checked by long-running steps. ``cancel()`` also kills registered subprocesses."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._procs: set[subprocess.Popen[str]] = set()
        self._lock = threading.Lock()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()
        with self._lock:
            for p in list(self._procs):
                if p.poll() is None:
                    p.kill()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise CancelledError("Cancelled by the user.")

    def _register(self, p: subprocess.Popen[str]) -> None:
        with self._lock:
            self._procs.add(p)
        if self.cancelled:  # cancel() raced with process start
            p.kill()

    def _unregister(self, p: subprocess.Popen[str]) -> None:
        with self._lock:
            self._procs.discard(p)


def run_ffmpeg(
    ffmpeg: Path,
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    duration: float | None = None,
    on_progress: Callable[[float], None] | None = None,
    cancel: CancelToken | None = None,
    timeout: float | None = None,
) -> None:
    """Run ffmpeg with ``-progress pipe:1``; report 0..1 progress when ``duration`` is known.

    ``timeout`` is wall-clock seconds for the whole run; None = no limit (long renders),
    cancellation is still possible through ``cancel``.
    """
    cmd = [str(ffmpeg), "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-progress", "pipe:1", *args]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
        encoding="utf-8",
        errors="replace",
    )
    if cancel:
        cancel._register(proc)
    stderr_chunks: list[str] = []
    # Drain stderr in a thread so a chatty ffmpeg never blocks on a full pipe.
    t = threading.Thread(target=lambda: stderr_chunks.append(proc.stderr.read() if proc.stderr else ""))
    t.start()
    timer = threading.Timer(timeout, proc.kill) if timeout else None
    if timer:
        timer.start()
    try:
        for line in proc.stdout or ():
            key, _, value = line.strip().partition("=")
            if key == "out_time_us" and duration and on_progress and value.isdigit():
                on_progress(min(1.0, int(value) / 1e6 / duration))
        proc.wait()
    finally:
        if timer:
            timer.cancel()
        t.join(timeout=5)
        if cancel:
            cancel._unregister(proc)
    if cancel and cancel.cancelled:
        raise CancelledError("Cancelled by the user.")
    if proc.returncode != 0:
        raise FfmpegFailedError(
            "ffmpeg failed.", details=f"exit {proc.returncode}: {''.join(stderr_chunks).strip()[-2000:]}"
        )
    if on_progress:
        on_progress(1.0)
