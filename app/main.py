"""FastAPI application entrypoint."""
from __future__ import annotations

from fastapi import FastAPI

from app.api.v1 import api_router
from app.core.errors import install_exception_handlers
from app.core.logging import RequestContextMiddleware, setup_logging

setup_logging()

_TAGS_METADATA = [
    {"name": "auth", "description": "Registration, login, and the current-user probe."},
    {"name": "projects", "description": "Org-scoped projects that group queues and jobs."},
    {"name": "queues", "description": "Queue config, pause/resume, retry policies, and stats."},
    {"name": "schedules", "description": "Recurring (cron) job templates."},
    {"name": "jobs", "description": "Submit, list, inspect, cancel, batch, and bulk-retry jobs."},
    {"name": "workers", "description": "Worker fleet and heartbeat history."},
    {"name": "dlq", "description": "Dead-letter queue: inspect, retry, discard."},
    {"name": "metrics", "description": "Throughput, success rate, latency percentiles, depth."},
    {"name": "health", "description": "Liveness probe."},
]

app = FastAPI(
    title="Distributed Job Scheduler",
    version="0.1.0",
    description=(
        "A Postgres-backed distributed job scheduling platform. Postgres is both "
        "the source of truth and the queue — jobs are claimed atomically with "
        "`SELECT ... FOR UPDATE SKIP LOCKED`. All routes below `/api/v1` require a "
        "JWT bearer token except `/auth/*`. Errors use a uniform envelope: "
        "`{\"error\": {\"code\", \"message\", \"details\"}}`."
    ),
    openapi_tags=_TAGS_METADATA,
    contact={"name": "Distributed Job Scheduler"},
    license_info={"name": "MIT"},
)

app.add_middleware(RequestContextMiddleware)
install_exception_handlers(app)
app.include_router(api_router)


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}
