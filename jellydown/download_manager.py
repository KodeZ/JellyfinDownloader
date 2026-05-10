"""Background download manager with cancellation."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .download import download_episode_job

log = logging.getLogger(__name__)

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"

EV_ADDED = "added"
EV_STATE = "state"
EV_PROGRESS = "progress"
EV_REMOVED = "removed"


@dataclass
class Job:
    id: str
    spec: dict
    filename: str
    output_path: Path
    status: str = QUEUED
    downloaded: int = 0
    total: int = 0
    speed: float = 0.0
    error: str = ""
    cancel_event: threading.Event = field(default_factory=threading.Event)
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    finished_at: float = 0.0


Subscriber = Callable[[str, Job], None]


class DownloadManager:
    """Submits download jobs to a thread pool and emits state changes.

    Subscribers run on worker threads; UI layers must marshal events to their
    main loop (Textual: App.call_from_thread). The classic CLI uses rich,
    which is thread-safe.
    """

    def __init__(self, base: str, api_key: str, user_id: str, cfg: dict,
                 workers: int | None = None):
        self.base = base
        self.api_key = api_key
        self.user_id = user_id
        self.cfg = cfg
        self.workers = max(1, int(workers if workers is not None
                                  else cfg.get("ParallelDownloads", 2)))
        self._executor = ThreadPoolExecutor(max_workers=self.workers)
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._subs: list[Subscriber] = []

    def subscribe(self, fn: Subscriber) -> None:
        self._subs.append(fn)

    def _emit(self, event: str, job: Job) -> None:
        for fn in list(self._subs):
            try:
                fn(event, job)
            except Exception:
                log.exception("subscriber raised")

    def jobs(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def submit(self, spec: dict) -> Job:
        job = Job(
            id=uuid.uuid4().hex,
            spec=spec,
            filename=spec["filename"],
            output_path=Path(spec["output_path"]),
        )
        with self._lock:
            self._jobs[job.id] = job
        self._emit(EV_ADDED, job)
        self._executor.submit(self._run, job)
        return job

    def cancel(self, job_id: str) -> None:
        job = self.get(job_id)
        if job is None or job.status in (DONE, FAILED, CANCELLED):
            return
        job.cancel_event.set()

    def cancel_all(self) -> None:
        for j in self.jobs():
            if j.status in (QUEUED, RUNNING):
                j.cancel_event.set()

    def remove(self, job_id: str) -> None:
        with self._lock:
            j = self._jobs.get(job_id)
            if j is None or j.status not in (DONE, FAILED, CANCELLED):
                return
            self._jobs.pop(job_id)
        self._emit(EV_REMOVED, j)

    def shutdown(self, wait: bool = True) -> None:
        self.cancel_all()
        self._executor.shutdown(wait=wait)

    def wait_all(self, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else time.time() + timeout
        while True:
            with self._lock:
                pending = any(j.status in (QUEUED, RUNNING)
                              for j in self._jobs.values())
            if not pending:
                return True
            if deadline is not None and time.time() >= deadline:
                return False
            time.sleep(0.05)

    def _set_status(self, job: Job, status: str, error: str = "") -> None:
        job.status = status
        if error:
            job.error = error
        if status == RUNNING:
            job.started_at = time.time()
        if status in (DONE, FAILED, CANCELLED):
            job.finished_at = time.time()
        self._emit(EV_STATE, job)

    def _progress_cb(self, job: Job):
        def cb(downloaded: int, total: int, speed: float) -> None:
            job.downloaded = downloaded
            if total:
                job.total = total
            job.speed = speed
            self._emit(EV_PROGRESS, job)
        return cb

    def _run(self, job: Job) -> None:
        if job.cancel_event.is_set():
            self._set_status(job, CANCELLED)
            return
        self._set_status(job, RUNNING)
        try:
            result = download_episode_job(
                job.spec, self.base, self.api_key, self.user_id, self.cfg,
                cancel_event=job.cancel_event,
                progress_cb=self._progress_cb(job),
            )
        except Exception as e:
            self._set_status(job, FAILED, error=str(e))
            return
        if result.get("ok"):
            self._set_status(job, DONE)
        elif result.get("cancelled"):
            self._set_status(job, CANCELLED)
        else:
            self._set_status(job, FAILED, error=result.get("error", "unknown"))
