"""FastAPI application entrypoint."""
from __future__ import annotations

from fastapi import FastAPI

from app.api.v1 import api_router
from app.core.errors import install_exception_handlers
from app.core.logging import RequestContextMiddleware, setup_logging

setup_logging()

app = FastAPI(
    title="Distributed Job Scheduler",
    version="0.1.0",
    description="A Postgres-backed distributed job scheduling platform.",
)

app.add_middleware(RequestContextMiddleware)
install_exception_handlers(app)
app.include_router(api_router)


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}
