"""Queue and retry-policy request/response schemas."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import RetryStrategy


class RetryPolicyIn(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    strategy: RetryStrategy = RetryStrategy.exponential
    base_delay_s: float = Field(default=5.0, ge=0)
    max_delay_s: float = Field(default=3600.0, ge=0)
    max_attempts: int = Field(default=5, ge=1, le=100)
    jitter: bool = True


class RetryPolicyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    name: str | None
    strategy: RetryStrategy
    base_delay_s: float
    max_delay_s: float
    max_attempts: int
    jitter: bool


class QueueCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    priority: int = 0
    concurrency_limit: int = Field(default=10, ge=1, le=10000)
    # Provide at most one of these: reference an existing policy, or define one inline.
    retry_policy_id: int | None = None
    retry_policy: RetryPolicyIn | None = None


class QueueUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    priority: int | None = None
    concurrency_limit: int | None = Field(default=None, ge=1, le=10000)
    retry_policy_id: int | None = None
    retry_policy: RetryPolicyIn | None = None


class QueueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    name: str
    priority: int
    concurrency_limit: int
    is_paused: bool
    retry_policy_id: int | None
    created_at: dt.datetime
    updated_at: dt.datetime


class QueueStats(BaseModel):
    queue_id: int
    total: int
    by_status: dict[str, int]
    oldest_queued_age_s: float | None
    avg_duration_ms: float | None
    in_flight: int  # claimed + running
