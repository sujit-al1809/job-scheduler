"""Job submission, listing, detail, and cancellation."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_org_id
from app.core.db import get_session
from app.models.enums import JobStatus
from app.schemas.common import Page
from app.schemas.job import (
    BulkRetryResponse,
    JobBatchCreate,
    JobBatchItem,
    JobBatchResponse,
    JobCreate,
    JobDetailResponse,
    JobResponse,
)
from app.services import job as job_service

router = APIRouter(tags=["jobs"])


@router.post(
    "/queues/{queue_id}/jobs",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a job (immediate or delayed; idempotent replay returns 200)",
)
async def create_job(
    queue_id: int,
    body: JobCreate,
    response: Response,
    org_id: int = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_session),
) -> JobResponse:
    job, created = await job_service.create_job(session, org_id, queue_id, body)
    response.status_code = (
        status.HTTP_201_CREATED if created else status.HTTP_200_OK
    )
    return JobResponse.model_validate(job)


@router.post(
    "/queues/{queue_id}/jobs/batch",
    response_model=JobBatchResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit an array of jobs atomically (single transaction)",
)
async def create_jobs_batch(
    queue_id: int,
    body: JobBatchCreate,
    org_id: int = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_session),
) -> JobBatchResponse:
    results = await job_service.batch_create_jobs(session, org_id, queue_id, body.jobs)
    items = [
        JobBatchItem(created=created, job=JobResponse.model_validate(job))
        for job, created in results
    ]
    created_count = sum(1 for _, c in results if c)
    return JobBatchResponse(
        items=items,
        total=len(items),
        created=created_count,
        replayed=len(items) - created_count,
    )


@router.post(
    "/queues/{queue_id}/jobs/retry-failed",
    response_model=BulkRetryResponse,
    summary="Bulk re-enqueue a queue's failed/dead jobs (fresh, attempts reset)",
)
async def retry_failed(
    queue_id: int,
    org_id: int = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_session),
) -> BulkRetryResponse:
    count = await job_service.retry_failed_jobs(session, org_id, queue_id)
    return BulkRetryResponse(requeued=count)


@router.get("/jobs", response_model=Page[JobResponse])
async def list_jobs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: JobStatus | None = None,
    queue_id: int | None = None,
    type: str | None = None,
    created_after: dt.datetime | None = None,
    created_before: dt.datetime | None = None,
    org_id: int = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_session),
) -> Page[JobResponse]:
    items, total = await job_service.list_jobs(
        session,
        org_id,
        limit=limit,
        offset=offset,
        status=status,
        queue_id=queue_id,
        type=type,
        created_after=created_after,
        created_before=created_before,
    )
    return Page[JobResponse](
        items=[JobResponse.model_validate(j) for j in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/jobs/{job_id}", response_model=JobDetailResponse)
async def get_job(
    job_id: int,
    org_id: int = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_session),
) -> JobDetailResponse:
    job = await job_service.get_job_detail(session, org_id, job_id)
    return JobDetailResponse.model_validate(job)


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(
    job_id: int,
    org_id: int = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_session),
) -> JobResponse:
    job = await job_service.cancel_job(session, org_id, job_id)
    return JobResponse.model_validate(job)
