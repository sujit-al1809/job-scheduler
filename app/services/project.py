"""Project business logic. Every query is scoped to the caller's organization;
cross-org access is indistinguishable from "not found" (404, no existence leak).
"""
from __future__ import annotations

import secrets

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.models import Project


def _generate_api_key() -> str:
    return secrets.token_hex(24)  # 48 hex chars


async def get_project_or_404(
    session: AsyncSession, org_id: int, project_id: int
) -> Project:
    project = await session.scalar(
        select(Project).where(
            Project.id == project_id, Project.org_id == org_id
        )
    )
    if project is None:
        raise NotFoundError("Project not found.", code="PROJECT_NOT_FOUND")
    return project


async def create_project(session: AsyncSession, org_id: int, name: str) -> Project:
    dupe = await session.scalar(
        select(Project.id).where(Project.org_id == org_id, Project.name == name)
    )
    if dupe is not None:
        raise ConflictError(
            "A project with this name already exists.", code="PROJECT_NAME_TAKEN"
        )
    project = Project(org_id=org_id, name=name, api_key=_generate_api_key())
    session.add(project)
    await session.flush()
    return project


async def list_projects(
    session: AsyncSession, org_id: int, limit: int, offset: int
) -> tuple[list[Project], int]:
    total = await session.scalar(
        select(func.count()).select_from(Project).where(Project.org_id == org_id)
    )
    rows = (
        await session.scalars(
            select(Project)
            .where(Project.org_id == org_id)
            .order_by(Project.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return list(rows), int(total or 0)


async def update_project(
    session: AsyncSession, org_id: int, project_id: int, name: str | None
) -> Project:
    project = await get_project_or_404(session, org_id, project_id)
    if name is not None and name != project.name:
        dupe = await session.scalar(
            select(Project.id).where(
                Project.org_id == org_id,
                Project.name == name,
                Project.id != project_id,
            )
        )
        if dupe is not None:
            raise ConflictError(
                "A project with this name already exists.",
                code="PROJECT_NAME_TAKEN",
            )
        project.name = name
    await session.flush()
    # updated_at is populated by an onupdate SQL expression; refresh so the caller
    # sees the DB-computed value without a lazy (sync) load during serialization.
    await session.refresh(project)
    return project


async def delete_project(
    session: AsyncSession, org_id: int, project_id: int
) -> None:
    project = await get_project_or_404(session, org_id, project_id)
    await session.delete(project)
    await session.flush()
