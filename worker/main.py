"""Worker process entrypoint.

Registers a worker, heartbeats, and (from commit 9) claims and executes jobs.
Run several instances to demonstrate distributed claiming.
"""
from __future__ import annotations

import asyncio
import logging
import signal

from app.core.logging import setup_logging
from worker.runtime import WorkerRuntime

logger = logging.getLogger("worker")


async def run() -> None:
    runtime = WorkerRuntime()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, runtime.request_stop)
        except NotImplementedError:  # Windows
            pass

    await runtime.run()


def main() -> None:
    setup_logging()
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
