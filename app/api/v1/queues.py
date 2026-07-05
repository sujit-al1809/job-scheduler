"""Queue CRUD, pause/resume, and stats — nested under a project."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_org_id
from app.core.db import get_session
from app.schemas.common import Page
from app.schemas.queue import (
    QueueCreate,
    QueueResponse,
    QueueStats,
    QueueUpdate,
)
from app.services import queue as queue_service

router = APIRouter(prefix="/projects/{project_id}/queues", tags=["queues"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=QueueResponse)
async def create_queue(
    project_id: int,
    body: QueueCreate,
    org_id: int = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_session),
) -> QueueResponse:
    queue = await queue_service.create_queue(session, org_id, project_id, body)
    return QueueResponse.model_validate(queue)


@router.get("", response_model=Page[QueueResponse])
async def list_queues(
    project_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    org_id: int = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_session),
) -> Page[QueueResponse]:
    items, total = await queue_service.list_queues(
        session, org_id, project_id, limit, offset
    )
    return Page[QueueResponse](
        items=[QueueResponse.model_validate(q) for q in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{queue_id}", response_model=QueueResponse)
async def get_queue(
    project_id: int,
    queue_id: int,
    org_id: int = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_session),
) -> QueueResponse:
    queue = await queue_service.get_queue_or_404(session, org_id, project_id, queue_id)
    return QueueResponse.model_validate(queue)


@router.patch("/{queue_id}", response_model=QueueResponse)
async def update_queue(
    project_id: int,
    queue_id: int,
    body: QueueUpdate,
    org_id: int = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_session),
) -> QueueResponse:
    queue = await queue_service.update_queue(
        session, org_id, project_id, queue_id, body
    )
    return QueueResponse.model_validate(queue)


@router.delete("/{queue_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_queue(
    project_id: int,
    queue_id: int,
    org_id: int = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await queue_service.delete_queue(session, org_id, project_id, queue_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{queue_id}/pause", response_model=QueueResponse)
async def pause_queue(
    project_id: int,
    queue_id: int,
    org_id: int = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_session),
) -> QueueResponse:
    queue = await queue_service.set_paused(session, org_id, project_id, queue_id, True)
    return QueueResponse.model_validate(queue)


@router.post("/{queue_id}/resume", response_model=QueueResponse)
async def resume_queue(
    project_id: int,
    queue_id: int,
    org_id: int = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_session),
) -> QueueResponse:
    queue = await queue_service.set_paused(session, org_id, project_id, queue_id, False)
    return QueueResponse.model_validate(queue)


@router.get("/{queue_id}/stats", response_model=QueueStats)
async def get_queue_stats(
    project_id: int,
    queue_id: int,
    org_id: int = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_session),
) -> QueueStats:
    stats = await queue_service.queue_stats(session, org_id, project_id, queue_id)
    return QueueStats(**stats)
