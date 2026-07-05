"""API v1 router aggregation."""
from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import auth, jobs, projects, queues, schedules

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(projects.router)
api_router.include_router(queues.router)
api_router.include_router(schedules.router)
api_router.include_router(jobs.router)
