"""Project metrics endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_org_id
from app.core.db import get_session
from app.schemas.metrics import ProjectMetrics
from app.services import metrics as metrics_service

router = APIRouter(prefix="/projects/{project_id}", tags=["metrics"])


@router.get(
    "/metrics",
    response_model=ProjectMetrics,
    summary="Project throughput, success rate, p50/p95 latency, and queue depth",
)
async def get_project_metrics(
    project_id: int,
    window_minutes: int = Query(60, ge=1, le=1440),
    org_id: int = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_session),
) -> ProjectMetrics:
    data = await metrics_service.project_metrics(
        session, org_id, project_id, window_minutes=window_minutes
    )
    return ProjectMetrics(**data)
