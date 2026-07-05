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

from app.core.config import settings
from app.core.db import SessionLocal
from app.models.enums import WorkerStatus
from app.services import worker as worker_service

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
    ) -> None:
        self.name = name or default_worker_name()
        self.concurrency = concurrency or settings.worker_concurrency
        self.poll_interval_s = poll_interval_s or settings.worker_poll_interval_s
        self.heartbeat_interval_s = (
            heartbeat_interval_s or settings.heartbeat_interval_s
        )
        self.worker_id: int | None = None
        self._stop = asyncio.Event()
        self._in_flight = 0

    @property
    def in_flight(self) -> int:
        return self._in_flight

    def request_stop(self) -> None:
        self._stop.set()

    async def _register(self) -> None:
        async with SessionLocal() as session:
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
                async with SessionLocal() as session:
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

    async def _claim_loop(self) -> None:
        # Extension point (commit 9): claim a batch, dispatch to the executor,
        # respecting free slots (concurrency - in_flight). For now the loop simply
        # idles until stop so heartbeats can be exercised.
        while not self._stop.is_set():
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
