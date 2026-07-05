"""Job handler registry + demo handlers.

Handlers are async callables keyed by job ``type``. Each receives a
:class:`JobContext` carrying ``(job_id, execution_id, payload)`` and a ``log()``
sink; anything logged is persisted to ``job_logs`` tied to the execution.

A handler signals failure by raising. Unregistered types fall back to a no-op
handler so generic jobs still complete.
"""
from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable

logger = logging.getLogger("worker.handler")


class JobContext:
    def __init__(
        self, *, job_id: int, execution_id: int, payload: dict, job_type: str
    ) -> None:
        self.job_id = job_id
        self.execution_id = execution_id
        self.payload = payload or {}
        self.job_type = job_type
        self.logs: list[tuple[str, str]] = []  # (level, message)

    def log(self, message: str, level: str = "info") -> None:
        self.logs.append((level, message))


Handler = Callable[[JobContext], Awaitable[None]]

HANDLERS: dict[str, Handler] = {}


def register_handler(job_type: str) -> Callable[[Handler], Handler]:
    def decorator(fn: Handler) -> Handler:
        HANDLERS[job_type] = fn
        return fn

    return decorator


async def _default_handler(ctx: JobContext) -> None:
    """Fallback for unregistered types: a no-op that optionally sleeps ``sleep_s``."""
    secs = _as_float(ctx.payload.get("sleep_s"), 0.0)
    if secs > 0:
        await asyncio.sleep(secs)


def get_handler(job_type: str) -> Handler:
    return HANDLERS.get(job_type, _default_handler)


def _as_float(value: object, default: float) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- #
# Demo handlers
# --------------------------------------------------------------------------- #
@register_handler("demo.sleep")
async def sleep_handler(ctx: JobContext) -> None:
    secs = _as_float(ctx.payload.get("seconds", ctx.payload.get("sleep_s", 0)), 0.0)
    ctx.log(f"sleeping for {secs}s")
    if secs > 0:
        await asyncio.sleep(secs)
    ctx.log("finished sleeping")


@register_handler("demo.always_fail")
async def always_fail_handler(ctx: JobContext) -> None:
    message = str(ctx.payload.get("message", "intentional failure"))
    ctx.log(f"about to fail: {message}", level="warning")
    raise RuntimeError(message)


@register_handler("demo.random_fail")
async def random_fail_handler(ctx: JobContext) -> None:
    """Fail with probability ``fail_rate`` — makes the retry pipeline demonstrable."""
    fail_rate = _as_float(ctx.payload.get("fail_rate", 0.5), 0.5)
    if random.random() < fail_rate:
        ctx.log(f"rolled a failure (fail_rate={fail_rate})", level="warning")
        raise RuntimeError(f"random failure (fail_rate={fail_rate})")
    ctx.log(f"rolled a success (fail_rate={fail_rate})")


@register_handler("demo.http_call")
async def http_call_handler(ctx: JobContext) -> None:
    """GET a URL from the payload. Real network — used for demos, not tests."""
    import httpx

    url = ctx.payload.get("url")
    if not url:
        ctx.log("no url provided; noop")
        return
    timeout = _as_float(ctx.payload.get("timeout_s", 10), 10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url)
        ctx.log(f"GET {url} -> {resp.status_code}")
        resp.raise_for_status()
