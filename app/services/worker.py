"""Worker registration, heartbeats, and status — shared by the worker process and API."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Worker, WorkerHeartbeat
from app.models.enums import WorkerStatus

_UTC = dt.timezone.utc


def _utcnow() -> dt.datetime:
    return dt.datetime.now(tz=_UTC)


async def register_worker(
    session: AsyncSession, name: str, concurrency: int
) -> Worker:
    now = _utcnow()
    worker = Worker(
        name=name,
        status=WorkerStatus.online,
        concurrency=concurrency,
        started_at=now,
        last_heartbeat_at=now,
    )
    session.add(worker)
    await session.commit()
    await session.refresh(worker)
    return worker


async def record_heartbeat(
    session: AsyncSession, worker_id: int, in_flight: int
) -> None:
    """Advance the worker's heartbeat and append a heartbeat sample (in-flight count)."""
    worker = await session.get(Worker, worker_id)
    if worker is None:
        return
    worker.last_heartbeat_at = _utcnow()
    session.add(WorkerHeartbeat(worker_id=worker_id, in_flight=in_flight))
    await session.commit()


async def set_worker_status(
    session: AsyncSession,
    worker_id: int,
    status: WorkerStatus,
    *,
    stopped: bool = False,
) -> None:
    worker = await session.get(Worker, worker_id)
    if worker is None:
        return
    worker.status = status
    if stopped:
        worker.stopped_at = _utcnow()
    await session.commit()


async def list_workers(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    status: WorkerStatus | None = None,
) -> tuple[list[Worker], int]:
    conditions = [] if status is None else [Worker.status == status]
    count_q = select(func.count()).select_from(Worker)
    list_q = select(Worker)
    for cond in conditions:
        count_q = count_q.where(cond)
        list_q = list_q.where(cond)
    total = await session.scalar(count_q)
    rows = (
        await session.scalars(
            list_q.order_by(Worker.id.desc()).limit(limit).offset(offset)
        )
    ).all()
    return list(rows), int(total or 0)


async def get_worker(session: AsyncSession, worker_id: int) -> Worker | None:
    return await session.get(Worker, worker_id)


async def list_heartbeats(
    session: AsyncSession, worker_id: int, *, limit: int, offset: int
) -> tuple[list[WorkerHeartbeat], int]:
    total = await session.scalar(
        select(func.count())
        .select_from(WorkerHeartbeat)
        .where(WorkerHeartbeat.worker_id == worker_id)
    )
    rows = (
        await session.scalars(
            select(WorkerHeartbeat)
            .where(WorkerHeartbeat.worker_id == worker_id)
            .order_by(WorkerHeartbeat.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return list(rows), int(total or 0)
