"""Background jobs (analyze / render) per project, with event fan-out for SSE subscribers."""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from snipscout.core.errors import SnipScoutError
from snipscout.core.models import JobEvent, JobState
from snipscout.core.procs import CancelToken

MAX_HISTORY = 200  # events kept so late subscribers can catch up


@dataclass
class Job:
    project_id: str
    kind: str  # "analyze" | "render"
    cancel: CancelToken = field(default_factory=CancelToken)
    thread: threading.Thread | None = None
    last: JobEvent | None = None

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()


class JobBusyError(SnipScoutError):
    code = "job_busy"


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._subs: dict[str, list[queue.Queue[JobEvent | None]]] = {}
        self._history: dict[str, list[JobEvent]] = {}
        self._lock = threading.Lock()

    def get(self, project_id: str) -> Job | None:
        return self._jobs.get(project_id)

    def running(self, project_id: str) -> bool:
        job = self._jobs.get(project_id)
        return bool(job and job.running)

    def publish(self, project_id: str, event: JobEvent) -> None:
        with self._lock:
            hist = self._history.setdefault(project_id, [])
            hist.append(event)
            del hist[:-MAX_HISTORY]
            job = self._jobs.get(project_id)
            if job:
                job.last = event
            subs = list(self._subs.get(project_id, []))
        for q in subs:
            q.put(event)

    def subscribe(self, project_id: str, replay: bool = True) -> queue.Queue[JobEvent | None]:
        q: queue.Queue[JobEvent | None] = queue.Queue()
        with self._lock:
            self._subs.setdefault(project_id, []).append(q)
            if replay:
                for e in self._history.get(project_id, []):
                    q.put(e)
        return q

    def unsubscribe(self, project_id: str, q: queue.Queue[JobEvent | None]) -> None:
        with self._lock:
            subs = self._subs.get(project_id, [])
            if q in subs:
                subs.remove(q)

    def start(
        self, project_id: str, kind: str, work: Callable[[Callable[[JobEvent], None], CancelToken], object]
    ) -> Job:
        """Run ``work(emit, cancel)`` in a thread. Errors are already reported by the pipeline as events."""
        with self._lock:
            current = self._jobs.get(project_id)
            if current and current.running:
                raise JobBusyError("This project is already being processed.", details=current.kind)
            job = Job(project_id=project_id, kind=kind)
            self._jobs[project_id] = job
            self._history[project_id] = []

        def run() -> None:
            try:
                work(lambda e: self.publish(project_id, e), job.cancel)
            except SnipScoutError as exc:
                # The pipeline already emitted a terminal event; make sure one exists.
                if not (job.last and job.last.state != JobState.RUNNING):
                    self.publish(
                        project_id,
                        JobEvent(
                            stage="done",
                            state=JobState.ERROR,
                            error_code=exc.code,
                            message=f"error.{exc.code}",
                        ),
                    )

        job.thread = threading.Thread(target=run, name=f"{kind}-{project_id}", daemon=True)
        job.thread.start()
        return job

    def cancel(self, project_id: str) -> bool:
        job = self._jobs.get(project_id)
        if job and job.running:
            job.cancel.cancel()
            return True
        return False

    def wait(self, project_id: str, timeout: float | None = None) -> None:
        job = self._jobs.get(project_id)
        if job and job.thread:
            job.thread.join(timeout)
