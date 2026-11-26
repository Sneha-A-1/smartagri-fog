"""Job runner: a process pool plus a progress pump that updates the database and live subscribers.

Behind a small interface (submit / cancel / start / stop) so it can later be swapped for Celery or
Dramatiq with Redis, without changing the routers.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import multiprocessing as mp
import queue as queue_mod
import time
from concurrent.futures import Future, ProcessPoolExecutor
from typing import Any

from sqlalchemy import select

from smartagri_api.config import Settings
from smartagri_api.db import session_scope
from smartagri_api.jobs.worker import JobCancelledError, run_plugin_job
from smartagri_api.models import Job, utcnow

log = logging.getLogger(__name__)

FINAL_STATES = {"succeeded", "failed", "cancelled", "interrupted"}


def job_to_dict(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "kind": job.kind,
        "plugin_id": job.plugin_id,
        "params": job.params,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "error": job.error,
        "data_origin": job.data_origin,
        "result_summary": job.result_summary,
        "has_result": job.result_path is not None,
        "project_id": job.project_id,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


class JobEventHub:
    """Fan-out of job events to WebSocket subscribers."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(q)

    def publish(self, event: dict[str, Any]) -> None:
        for q in list(self._subscribers):
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(event)


class JobRunner:
    def __init__(self, settings: Settings, hub: JobEventHub) -> None:
        self.settings = settings
        self.hub = hub
        self._futures: dict[str, Future[dict[str, Any]]] = {}
        self._last_db_write: dict[str, float] = {}
        self._finished: set[str] = set()
        self._stopping = False

    async def start(self) -> None:
        ctx = mp.get_context("spawn")  # same behaviour on Windows, macOS and Linux
        self._manager = ctx.Manager()
        self._queue = self._manager.Queue()
        self._cancel_flags = self._manager.dict()
        self._executor = ProcessPoolExecutor(max_workers=self.settings.job_workers, mp_context=ctx)
        self._loop = asyncio.get_running_loop()
        self._mark_interrupted_jobs()
        self._pump_task = asyncio.create_task(self._pump())

    async def stop(self) -> None:
        self._stopping = True
        for job_id in list(self._futures):
            self._cancel_flags[job_id] = True
        try:
            await self._pump_task
        except asyncio.CancelledError:
            self._pump_task.cancel()  # forced quit: skip waiting for progress messages
        self._executor.shutdown(wait=True, cancel_futures=True)
        self._manager.shutdown()

    def submit(self, job_id: str, plugin_id: str, params: dict[str, Any]) -> None:
        fut = self._executor.submit(
            run_plugin_job,
            job_id,
            plugin_id,
            params,
            str(self.settings.resolved_results_dir),
            self._queue,
            self._cancel_flags,
        )
        self._futures[job_id] = fut
        fut.add_done_callback(lambda f: self._loop.call_soon_threadsafe(self._on_done, job_id, f))

    def cancel(self, job_id: str) -> bool:
        fut = self._futures.get(job_id)
        if fut is None:
            return False
        self._cancel_flags[job_id] = True
        fut.cancel()  # succeeds only if the job has not started yet; otherwise the flag stops it
        return True

    # --- internals -------------------------------------------------------------------------

    async def _pump(self) -> None:
        while not self._stopping or self._futures:
            try:
                msg = await asyncio.to_thread(self._queue.get, True, 0.25)
            except queue_mod.Empty:
                if self._stopping and all(f.done() for f in self._futures.values()):
                    break
                continue
            except (EOFError, BrokenPipeError, ConnectionError, OSError):
                break
            self._apply_progress(msg)

    def _apply_progress(self, msg: dict[str, Any]) -> None:
        job_id = msg["job_id"]
        if job_id in self._finished:
            return
        now = time.monotonic()
        event = {
            "type": "job.progress",
            "job_id": job_id,
            "progress": msg["fraction"],
            "message": msg["message"],
            "status": "running",
        }
        if now - self._last_db_write.get(job_id, 0.0) >= 0.5 or msg["fraction"] in (0.0, 1.0):
            self._last_db_write[job_id] = now
            with session_scope() as s:
                job = s.get(Job, job_id)
                if job is None or job.status in FINAL_STATES:
                    return
                if job.status == "queued":
                    job.status, job.started_at = "running", utcnow()
                job.progress, job.message = msg["fraction"], msg["message"][:500]
                s.commit()
        self.hub.publish(event)

    def _on_done(self, job_id: str, fut: Future[dict[str, Any]]) -> None:
        self._futures.pop(job_id, None)
        self._finished.add(job_id)
        self._cancel_flags.pop(job_id, None)
        with session_scope() as s:
            job = s.get(Job, job_id)
            if job is None:
                return
            job.finished_at = utcnow()
            exc = None if fut.cancelled() else fut.exception()
            if fut.cancelled() or isinstance(exc, JobCancelledError):
                job.status, job.message = "cancelled", "Cancelled by user"
            elif exc is not None:
                job.status, job.error, job.message = "failed", str(exc), "Failed"
            else:
                out = fut.result()
                job.status, job.progress, job.message = "succeeded", 1.0, "Finished"
                job.result_path = out["result_path"]
                job.result_summary = out["summary"]
                job.data_origin = out["data_origin"]
            s.commit()
            self.hub.publish({"type": "job.finished", "job": job_to_dict(job)})

    def _mark_interrupted_jobs(self) -> None:
        with session_scope() as s:
            for job in s.scalars(select(Job).where(Job.status.in_(["queued", "running"]))):
                job.status = "interrupted"
                job.error = "The API stopped before this job finished. Start it again."
                job.finished_at = utcnow()
            s.commit()
