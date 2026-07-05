"""Dead-letter-queue endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_org_id
from app.core.db import get_session
from app.schemas.common import Page
from app.schemas.dlq import DeadLetterJobResponse
from app.schemas.job import JobResponse
from app.services import dlq as dlq_service

router = APIRouter(tags=["dlq"])


@router.get("/projects/{project_id}/dlq", response_model=Page[DeadLetterJobResponse])
async def list_dlq(
    project_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    org_id: int = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_session),
) -> Page[DeadLetterJobResponse]:
    items, total = await dlq_service.list_dlq(
        session, org_id, project_id, limit, offset
    )
    return Page[DeadLetterJobResponse](
        items=[DeadLetterJobResponse.model_validate(e) for e in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/dlq/{dlq_id}/retry", response_model=JobResponse)
async def retry_dlq(
    dlq_id: int,
    org_id: int = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_session),
) -> JobResponse:
    job = await dlq_service.retry_dlq(session, org_id, dlq_id)
    return JobResponse.model_validate(job)


@router.delete("/dlq/{dlq_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dlq(
    dlq_id: int,
    org_id: int = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await dlq_service.delete_dlq(session, org_id, dlq_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
