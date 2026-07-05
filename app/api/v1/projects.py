"""Project CRUD, scoped to the caller's organization."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_org_id
from app.core.db import get_session
from app.schemas.common import Page
from app.schemas.project import ProjectCreate, ProjectResponse, ProjectUpdate
from app.services import project as project_service

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ProjectResponse)
async def create_project(
    body: ProjectCreate,
    org_id: int = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_session),
) -> ProjectResponse:
    project = await project_service.create_project(session, org_id, body.name)
    return ProjectResponse.model_validate(project)


@router.get("", response_model=Page[ProjectResponse])
async def list_projects(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    org_id: int = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_session),
) -> Page[ProjectResponse]:
    items, total = await project_service.list_projects(session, org_id, limit, offset)
    return Page[ProjectResponse](
        items=[ProjectResponse.model_validate(p) for p in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: int,
    org_id: int = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_session),
) -> ProjectResponse:
    project = await project_service.get_project_or_404(session, org_id, project_id)
    return ProjectResponse.model_validate(project)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: int,
    body: ProjectUpdate,
    org_id: int = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_session),
) -> ProjectResponse:
    project = await project_service.update_project(
        session, org_id, project_id, body.name
    )
    return ProjectResponse.model_validate(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: int,
    org_id: int = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await project_service.delete_project(session, org_id, project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
