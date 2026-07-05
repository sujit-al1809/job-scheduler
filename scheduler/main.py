"""Scheduler process.

A single async loop that, every ``SCHEDULER_POLL_INTERVAL_S``:

1. promotes due ``scheduled`` jobs to ``queued``, and
2. materializes one job per due cron template.

Run several instances safely — ``FOR UPDATE SKIP LOCKED`` ensures each due row is
handled exactly once. The dead-worker reaper is added to this loop in a later
commit.
"""
from __future__ import annotations

import asyncio
import logging
import signal

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.logging import setup_logging
from app.services.scheduler_engine import (
    materialize_due_cron_jobs,
    promote_due_scheduled_jobs,
)

logger = logging.getLogger("scheduler")


async def _tick() -> None:
    async with SessionLocal() as session:
        promoted = await promote_due_scheduled_jobs(session)
    async with SessionLocal() as session:
        materialized = await materialize_due_cron_jobs(session)
    if promoted or materialized:
        logger.info(
            "scheduler_tick",
            extra={
                "extra_fields": {
                    "promoted": promoted,
                    "materialized": len(materialized),
                }
            },
        )


async def run() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows: fall back to KeyboardInterrupt
            pass

    logger.info("scheduler_starting", extra={"extra_fields": {
        "poll_interval_s": settings.scheduler_poll_interval_s
    }})
    while not stop.is_set():
        try:
            await _tick()
        except Exception:
            logger.exception("scheduler_tick_failed")
        try:
            await asyncio.wait_for(
                stop.wait(), timeout=settings.scheduler_poll_interval_s
            )
        except asyncio.TimeoutError:
            pass
    logger.info("scheduler_stopped")


def main() -> None:
    setup_logging()
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
