"""Atomic job claiming — the heart of the whole system.

This is the ONE sanctioned place that sets ``status = 'claimed'`` in bulk. It uses
``FOR UPDATE ... SKIP LOCKED`` so N workers claiming the same queue concurrently
each get a disjoint set of jobs — no job is ever handed to two workers.

The query is exactly the pattern mandated in CLAUDE.md (invariant 1), plus the
per-queue concurrency exclusion (invariant 2): a queue is skipped while it already
has ``concurrency_limit`` jobs in flight. That limit is a *soft* limit under READ
COMMITTED (see docs/design-decisions.md).
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# ``priority DESC, run_at ASC, id ASC`` matches the partial index ix_jobs_claim,
# so the planner satisfies ORDER BY + LIMIT straight from the index.
_CLAIM_TEMPLATE = """
UPDATE jobs
SET status = 'claimed', worker_id = :worker_id, claimed_at = now()
WHERE id IN (
    SELECT j.id
    FROM jobs j
    JOIN queues q ON q.id = j.queue_id
    WHERE j.status = 'queued'
      AND j.run_at <= now()
      AND q.is_paused = false
      {project_filter}
      AND (
          SELECT count(*)
          FROM jobs c
          WHERE c.queue_id = q.id
            AND c.status IN ('claimed', 'running')
      ) < q.concurrency_limit
    ORDER BY j.priority DESC, j.run_at ASC, j.id ASC
    LIMIT :batch_size
    FOR UPDATE OF j SKIP LOCKED
)
RETURNING id
"""


async def claim_jobs(
    session: AsyncSession,
    worker_id: int,
    *,
    batch_size: int,
    project_ids: list[int] | None = None,
) -> list[int]:
    """Atomically claim up to ``batch_size`` due jobs for ``worker_id``.

    Returns the claimed job ids. The caller owns the transaction and must commit
    (a short claim transaction), which releases the row locks and publishes the
    ``claimed`` status so other workers skip these rows.
    """
    if batch_size <= 0:
        return []

    params: dict[str, object] = {"worker_id": worker_id, "batch_size": batch_size}
    if project_ids:
        project_filter = "AND q.project_id = ANY(:project_ids)"
        params["project_ids"] = project_ids
    else:
        project_filter = ""

    sql = text(_CLAIM_TEMPLATE.format(project_filter=project_filter))
    result = await session.execute(sql, params)
    return [row[0] for row in result.all()]
