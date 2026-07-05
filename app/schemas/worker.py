"""Worker and heartbeat response schemas."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict

from app.models.enums import WorkerStatus


class WorkerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    status: WorkerStatus
    concurrency: int | None
    started_at: dt.datetime
    last_heartbeat_at: dt.datetime
    stopped_at: dt.datetime | None
    created_at: dt.datetime


class WorkerHeartbeatResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    worker_id: int
    in_flight: int
    created_at: dt.datetime
