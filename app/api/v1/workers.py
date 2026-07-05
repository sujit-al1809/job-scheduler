"""Worker + heartbeat read endpoints for the dashboard (auth required)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_session
from app.core.errors import NotFoundError
from app.models import User
from app.models.enums import WorkerStatus
from app.schemas.common import Page
from app.schemas.worker import WorkerHeartbeatResponse, WorkerResponse
from app.services import worker as worker_service

router = APIRouter(prefix="/workers", tags=["workers"])


@router.get("", response_model=Page[WorkerResponse])
async def list_workers(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: WorkerStatus | None = None,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Page[WorkerResponse]:
    items, total = await worker_service.list_workers(
        session, limit=limit, offset=offset, status=status
    )
    return Page[WorkerResponse](
        items=[WorkerResponse.model_validate(w) for w in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{worker_id}", response_model=WorkerResponse)
async def get_worker(
    worker_id: int,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> WorkerResponse:
    worker = await worker_service.get_worker(session, worker_id)
    if worker is None:
        raise NotFoundError("Worker not found.", code="WORKER_NOT_FOUND")
    return WorkerResponse.model_validate(worker)


@router.get("/{worker_id}/heartbeats", response_model=Page[WorkerHeartbeatResponse])
async def list_heartbeats(
    worker_id: int,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Page[WorkerHeartbeatResponse]:
    items, total = await worker_service.list_heartbeats(
        session, worker_id, limit=limit, offset=offset
    )
    return Page[WorkerHeartbeatResponse](
        items=[WorkerHeartbeatResponse.model_validate(hb) for hb in items],
        total=total,
        limit=limit,
        offset=offset,
    )
