"""Metrics response schemas."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel


class ThroughputBucket(BaseModel):
    minute: dt.datetime
    completed: int
    failed: int


class QueueDepth(BaseModel):
    queue_id: int
    name: str
    depth: int  # jobs waiting (queued)
    in_flight: int  # claimed + running


class ProjectMetrics(BaseModel):
    window_minutes: int
    total_completed: int
    total_failed: int
    success_rate: float | None
    p50_duration_ms: float | None
    p95_duration_ms: float | None
    throughput_per_minute: list[ThroughputBucket]
    queue_depths: list[QueueDepth]
