"""Dead-letter-queue operations: list, retry (fresh re-enqueue), discard."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models import DeadLetterJob, Job, Project
from app.models.enums import JobStatus
from app.services import job_state
from app.services.project import get_project_or_404

_UTC = dt.timezone.utc


async def list_dlq(
    session: AsyncSession, org_id: int, project_id: int, limit: int, offset: int
) -> tuple[list[DeadLetterJob], int]:
    await get_project_or_404(session, org_id, project_id)  # enforce ownership
    total = await session.scalar(
        select(func.count())
        .select_from(DeadLetterJob)
        .where(DeadLetterJob.project_id == project_id)
    )
    rows = (
        await session.scalars(
            select(DeadLetterJob)
            .where(DeadLetterJob.project_id == project_id)
            .order_by(DeadLetterJob.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return list(rows), int(total or 0)


async def _get_dlq_for_org(
    session: AsyncSession, org_id: int, dlq_id: int
) -> DeadLetterJob:
    entry = await session.scalar(
        select(DeadLetterJob)
        .join(Project, Project.id == DeadLetterJob.project_id)
        .where(DeadLetterJob.id == dlq_id, Project.org_id == org_id)
    )
    if entry is None:
        raise NotFoundError("Dead-letter entry not found.", code="DLQ_NOT_FOUND")
    return entry


async def retry_dlq(session: AsyncSession, org_id: int, dlq_id: int) -> Job:
    """Re-enqueue the dead job fresh (attempts reset), then drop the DLQ entry."""
    entry = await _get_dlq_for_org(session, org_id, dlq_id)
    job = await session.get(Job, entry.job_id)
    if job is None:
        # Original job was deleted; nothing to re-enqueue.
        await session.delete(entry)
        await session.flush()
        raise NotFoundError("Original job no longer exists.", code="JOB_NOT_FOUND")

    job.attempts = 0
    job.last_error = None
    await job_state.transition(
        session,
        job,
        JobStatus.queued,
        run_at=dt.datetime.now(tz=_UTC),
        message="requeued_from_dlq",
    )
    await session.delete(entry)
    await session.flush()
    await session.refresh(job)
    return job


async def delete_dlq(session: AsyncSession, org_id: int, dlq_id: int) -> None:
    entry = await _get_dlq_for_org(session, org_id, dlq_id)
    await session.delete(entry)
    await session.flush()
