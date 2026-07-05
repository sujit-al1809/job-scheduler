"""CRUD for recurring schedules (cron templates), org-scoped through the queue."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models import ScheduledJob
from app.schemas.schedule import ScheduleCreate, ScheduleUpdate
from app.services.queue import get_queue_for_org
from app.services.scheduler_engine import next_cron_time

_UTC = dt.timezone.utc


async def create_schedule(
    session: AsyncSession, org_id: int, queue_id: int, body: ScheduleCreate
) -> ScheduledJob:
    await get_queue_for_org(session, org_id, queue_id)  # enforce ownership
    now = dt.datetime.now(tz=_UTC)
    schedule = ScheduledJob(
        queue_id=queue_id,
        name=body.name,
        type=body.type,
        cron_expr=body.cron_expr,
        payload=body.payload,
        priority=body.priority,
        next_run_at=next_cron_time(body.cron_expr, now),
        is_active=True,
    )
    session.add(schedule)
    await session.flush()
    await session.refresh(schedule)
    return schedule


async def get_schedule_or_404(
    session: AsyncSession, org_id: int, queue_id: int, schedule_id: int
) -> ScheduledJob:
    await get_queue_for_org(session, org_id, queue_id)
    schedule = await session.scalar(
        select(ScheduledJob).where(
            ScheduledJob.id == schedule_id, ScheduledJob.queue_id == queue_id
        )
    )
    if schedule is None:
        raise NotFoundError("Schedule not found.", code="SCHEDULE_NOT_FOUND")
    return schedule


async def list_schedules(
    session: AsyncSession, org_id: int, queue_id: int, limit: int, offset: int
) -> tuple[list[ScheduledJob], int]:
    await get_queue_for_org(session, org_id, queue_id)
    total = await session.scalar(
        select(func.count())
        .select_from(ScheduledJob)
        .where(ScheduledJob.queue_id == queue_id)
    )
    rows = (
        await session.scalars(
            select(ScheduledJob)
            .where(ScheduledJob.queue_id == queue_id)
            .order_by(ScheduledJob.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return list(rows), int(total or 0)


async def update_schedule(
    session: AsyncSession,
    org_id: int,
    queue_id: int,
    schedule_id: int,
    body: ScheduleUpdate,
) -> ScheduledJob:
    schedule = await get_schedule_or_404(session, org_id, queue_id, schedule_id)
    if body.name is not None:
        schedule.name = body.name
    if body.type is not None:
        schedule.type = body.type
    if body.payload is not None:
        schedule.payload = body.payload
    if body.priority is not None:
        schedule.priority = body.priority
    if body.cron_expr is not None:
        schedule.cron_expr = body.cron_expr
        # Recompute the next fire time from the new expression.
        schedule.next_run_at = next_cron_time(
            body.cron_expr, dt.datetime.now(tz=_UTC)
        )
    await session.flush()
    await session.refresh(schedule)
    return schedule


async def set_active(
    session: AsyncSession,
    org_id: int,
    queue_id: int,
    schedule_id: int,
    active: bool,
) -> ScheduledJob:
    schedule = await get_schedule_or_404(session, org_id, queue_id, schedule_id)
    schedule.is_active = active
    if active:
        # Resume from now so we don't burst-fire missed ticks.
        schedule.next_run_at = next_cron_time(
            schedule.cron_expr, dt.datetime.now(tz=_UTC)
        )
    await session.flush()
    await session.refresh(schedule)
    return schedule


async def delete_schedule(
    session: AsyncSession, org_id: int, queue_id: int, schedule_id: int
) -> None:
    schedule = await get_schedule_or_404(session, org_id, queue_id, schedule_id)
    await session.delete(schedule)
    await session.flush()
