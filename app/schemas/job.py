"""Job request/response schemas."""
from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ExecutionStatus, JobStatus


class JobCreate(BaseModel):
    type: str = Field(min_length=1, max_length=255)
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int | None = None  # defaults to the queue's priority
    delay_s: float | None = Field(default=None, ge=0)  # >0 => scheduled
    max_attempts: int | None = Field(default=None, ge=1, le=100)
    idempotency_key: str | None = Field(default=None, max_length=255)


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    queue_id: int
    project_id: int
    type: str
    payload: dict[str, Any]
    status: JobStatus
    priority: int
    run_at: dt.datetime
    attempts: int
    max_attempts: int
    idempotency_key: str | None
    worker_id: int | None
    claimed_at: dt.datetime | None
    started_at: dt.datetime | None
    finished_at: dt.datetime | None
    last_error: str | None
    created_at: dt.datetime
    updated_at: dt.datetime


class JobExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    attempt: int
    worker_id: int | None
    status: ExecutionStatus
    error: str | None
    started_at: dt.datetime
    finished_at: dt.datetime | None
    duration_ms: int | None


class JobLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    execution_id: int | None
    level: str
    message: str
    created_at: dt.datetime


class JobDetailResponse(JobResponse):
    executions: list[JobExecutionResponse]
    logs: list[JobLogResponse]


class JobBatchCreate(BaseModel):
    jobs: list[JobCreate] = Field(min_length=1, max_length=1000)


class JobBatchItem(BaseModel):
    created: bool  # False => idempotent replay of an existing job
    job: JobResponse


class JobBatchResponse(BaseModel):
    items: list[JobBatchItem]
    total: int
    created: int
    replayed: int
