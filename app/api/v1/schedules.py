"""Recurring-schedule (cron) CRUD, nested under a queue."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_org_id
from app.core.db import get_session
from app.schemas.common import Page
from app.schemas.schedule import ScheduleCreate, ScheduleResponse, ScheduleUpdate
from app.services import schedule as schedule_service

router = APIRouter(prefix="/queues/{queue_id}/schedules", tags=["schedules"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ScheduleResponse)
async def create_schedule(
    queue_id: int,
    body: ScheduleCreate,
    org_id: int = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_session),
) -> ScheduleResponse:
    schedule = await schedule_service.create_schedule(session, org_id, queue_id, body)
    return ScheduleResponse.model_validate(schedule)


@router.get("", response_model=Page[ScheduleResponse])
async def list_schedules(
    queue_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    org_id: int = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_session),
) -> Page[ScheduleResponse]:
    items, total = await schedule_service.list_schedules(
        session, org_id, queue_id, limit, offset
    )
    return Page[ScheduleResponse](
        items=[ScheduleResponse.model_validate(s) for s in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{schedule_id}", response_model=ScheduleResponse)
async def get_schedule(
    queue_id: int,
    schedule_id: int,
    org_id: int = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_session),
) -> ScheduleResponse:
    schedule = await schedule_service.get_schedule_or_404(
        session, org_id, queue_id, schedule_id
    )
    return ScheduleResponse.model_validate(schedule)


@router.patch("/{schedule_id}", response_model=ScheduleResponse)
async def update_schedule(
    queue_id: int,
    schedule_id: int,
    body: ScheduleUpdate,
    org_id: int = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_session),
) -> ScheduleResponse:
    schedule = await schedule_service.update_schedule(
        session, org_id, queue_id, schedule_id, body
    )
    return ScheduleResponse.model_validate(schedule)


@router.post("/{schedule_id}/pause", response_model=ScheduleResponse)
async def pause_schedule(
    queue_id: int,
    schedule_id: int,
    org_id: int = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_session),
) -> ScheduleResponse:
    schedule = await schedule_service.set_active(
        session, org_id, queue_id, schedule_id, False
    )
    return ScheduleResponse.model_validate(schedule)


@router.post("/{schedule_id}/activate", response_model=ScheduleResponse)
async def activate_schedule(
    queue_id: int,
    schedule_id: int,
    org_id: int = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_session),
) -> ScheduleResponse:
    schedule = await schedule_service.set_active(
        session, org_id, queue_id, schedule_id, True
    )
    return ScheduleResponse.model_validate(schedule)


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(
    queue_id: int,
    schedule_id: int,
    org_id: int = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await schedule_service.delete_schedule(session, org_id, queue_id, schedule_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
