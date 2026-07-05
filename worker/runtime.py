"""Worker runtime: registration, heartbeat loop, and the claim/execute loop.

This commit establishes registration + heartbeats and the loop scaffolding. Atomic
claiming (commit 9), the execution engine (commit 10), retries (commit 11), and
graceful drain + reaper cooperation (commit 12) slot into the marked extension
points below.
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.db import SessionLocal
from app.models.enums import WorkerStatus
from app.services import worker as worker_service
from worker.claim import claim_jobs
from worker.executor import execute_job

logger = logging.getLogger("worker")


def default_worker_name() -> str:
    return f"worker-{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"


class WorkerRuntime:
    def __init__(
        self,
        *,
        name: str | None = None,
        concurrency: int | None = None,
        poll_interval_s: float | None = None,
        heartbeat_interval_s: float | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        project_ids: list[int] | None = None,
    ) -> None:
        self.name = name or default_worker_name()
        self.concurrency = concurrency or settings.worker_concurrency
        self.poll_interval_s = poll_interval_s or settings.worker_poll_interval_s
        self.heartbeat_interval_s = (
            heartbeat_interval_s or settings.heartbeat_interval_s
        )
        self.project_ids = project_ids
        self._session_factory = session_factory or SessionLocal
        self.worker_id: int | None = None
        self._stop = asyncio.Event()
        self._in_flight = 0
        self._tasks: set[asyncio.Task] = set()

    @property
    def in_flight(self) -> int:
        return self._in_flight

    def request_stop(self) -> None:
        self._stop.set()

    async def _register(self) -> None:
        async with self._session_factory() as session:
            worker = await worker_service.register_worker(
                session, self.name, self.concurrency
            )
            self.worker_id = worker.id
        logger.info(
            "worker_registered",
            extra={"extra_fields": {"worker_id": self.worker_id, "name": self.name}},
        )

    async def _heartbeat_loop(self) -> None:
        assert self.worker_id is not None
        while not self._stop.is_set():
            try:
                async with self._session_factory() as session:
                    await worker_service.record_heartbeat(
                        session, self.worker_id, self._in_flight
                    )
            except Exception:
                logger.exception("heartbeat_failed")
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self.heartbeat_interval_s
                )
            except asyncio.TimeoutError:
                pass

    async def _execute_and_track(self, job_id: int) -> None:
        assert self.worker_id is not None
        try:
            await execute_job(self._session_factory, self.worker_id, job_id)
        except Exception:
            logger.exception("execute_job_failed", extra={"extra_fields": {"job_id": job_id}})
        finally:
            self._in_flight -= 1

    async def _claim_loop(self) -> None:
        assert self.worker_id is not None
        while not self._stop.is_set():
            free_slots = self.concurrency - self._in_flight
            batch = min(free_slots, settings.worker_claim_batch_size)
            claimed: list[int] = []
            if batch > 0:
                try:
                    async with self._session_factory() as session:
                        claimed = await claim_jobs(
                            session,
                            self.worker_id,
                            batch_size=batch,
                            project_ids=self.project_ids,
                        )
                        await session.commit()
                except Exception:
                    logger.exception("claim_failed")

            for job_id in claimed:
                self._in_flight += 1
                task = asyncio.create_task(self._execute_and_track(job_id))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)

            # If we filled a full batch there may be more ready work; poll again
            # immediately. Otherwise wait for the poll interval (or an early stop).
            if claimed and len(claimed) == batch:
                continue
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self.poll_interval_s
                )
            except asyncio.TimeoutError:
                pass

    async def _shutdown(self) -> None:
        if self.worker_id is None:
            return
        async with SessionLocal() as session:
            await worker_service.set_worker_status(
                session, self.worker_id, WorkerStatus.stopped, stopped=True
            )
        logger.info("worker_stopped", extra={"extra_fields": {"worker_id": self.worker_id}})

    async def run(self) -> None:
        await self._register()
        logger.info(
            "worker_starting",
            extra={
                "extra_fields": {
                    "worker_id": self.worker_id,
                    "concurrency": self.concurrency,
                    "poll_interval_s": self.poll_interval_s,
                }
            },
        )
        try:
            await asyncio.gather(self._heartbeat_loop(), self._claim_loop())
        finally:
            await self._shutdown()
