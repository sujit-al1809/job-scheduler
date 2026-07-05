"""FastAPI application entrypoint."""
from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(
    title="Distributed Job Scheduler",
    version="0.1.0",
    description="A Postgres-backed distributed job scheduling platform.",
)


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}
