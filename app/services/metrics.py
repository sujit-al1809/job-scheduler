"""Project metrics, all derived from ``job_executions`` (never stored redundantly).

Throughput is bucketed per minute over a trailing window; success rate and p50/p95
duration come from the same window; queue depth is a point-in-time snapshot.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.project import get_project_or_404

_UTC = dt.timezone.utc

_WINDOW_SQL = text(
    """
    SELECT
        count(*) FILTER (WHERE je.status = 'completed') AS completed,
        count(*) FILTER (WHERE je.status IN ('failed', 'timeout')) AS failed,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY je.duration_ms)
            FILTER (WHERE je.status = 'completed' AND je.duration_ms IS NOT NULL)
            AS p50,
        percentile_cont(0.95) WITHIN GROUP (ORDER BY je.duration_ms)
            FILTER (WHERE je.status = 'completed' AND je.duration_ms IS NOT NULL)
            AS p95
    FROM job_executions je
    JOIN jobs j ON j.id = je.job_id
    WHERE j.project_id = :pid AND je.finished_at >= :since
    """
)

_THROUGHPUT_SQL = text(
    """
    SELECT
        date_trunc('minute', je.finished_at) AS minute,
        count(*) FILTER (WHERE je.status = 'completed') AS completed,
        count(*) FILTER (WHERE je.status IN ('failed', 'timeout')) AS failed
    FROM job_executions je
    JOIN jobs j ON j.id = je.job_id
    WHERE j.project_id = :pid AND je.finished_at >= :since
    GROUP BY minute
    ORDER BY minute
    """
)

_DEPTH_SQL = text(
    """
    SELECT
        q.id AS queue_id,
        q.name AS name,
        count(j.id) FILTER (WHERE j.status = 'queued') AS depth,
        count(j.id) FILTER (WHERE j.status IN ('claimed', 'running')) AS in_flight
    FROM queues q
    LEFT JOIN jobs j ON j.queue_id = q.id
    WHERE q.project_id = :pid
    GROUP BY q.id, q.name
    ORDER BY q.id
    """
)


async def project_metrics(
    session: AsyncSession, org_id: int, project_id: int, *, window_minutes: int = 60
) -> dict:
    await get_project_or_404(session, org_id, project_id)  # enforce ownership
    since = dt.datetime.now(tz=_UTC) - dt.timedelta(minutes=window_minutes)
    params = {"pid": project_id, "since": since}

    window = (await session.execute(_WINDOW_SQL, params)).one()
    completed = int(window.completed or 0)
    failed = int(window.failed or 0)
    resolved = completed + failed
    success_rate = (completed / resolved) if resolved > 0 else None

    throughput = [
        {
            "minute": row.minute,
            "completed": int(row.completed or 0),
            "failed": int(row.failed or 0),
        }
        for row in (await session.execute(_THROUGHPUT_SQL, params)).all()
    ]

    queue_depths = [
        {
            "queue_id": row.queue_id,
            "name": row.name,
            "depth": int(row.depth or 0),
            "in_flight": int(row.in_flight or 0),
        }
        for row in (await session.execute(_DEPTH_SQL, {"pid": project_id})).all()
    ]

    return {
        "window_minutes": window_minutes,
        "total_completed": completed,
        "total_failed": failed,
        "success_rate": success_rate,
        "p50_duration_ms": float(window.p50) if window.p50 is not None else None,
        "p95_duration_ms": float(window.p95) if window.p95 is not None else None,
        "throughput_per_minute": throughput,
        "queue_depths": queue_depths,
    }
