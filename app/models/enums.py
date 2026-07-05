"""Enumerated types used across the schema, backed by native Postgres enums."""
from __future__ import annotations

import enum


class JobStatus(str, enum.Enum):
    scheduled = "scheduled"
    queued = "queued"
    claimed = "claimed"
    running = "running"
    completed = "completed"
    failed = "failed"
    dead = "dead"
    cancelled = "cancelled"


class ExecutionStatus(str, enum.Enum):
    running = "running"
    completed = "completed"
    failed = "failed"
    timeout = "timeout"


class WorkerStatus(str, enum.Enum):
    online = "online"
    draining = "draining"
    stopped = "stopped"
    dead = "dead"


class RetryStrategy(str, enum.Enum):
    fixed = "fixed"
    linear = "linear"
    exponential = "exponential"


class OrgRole(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    member = "member"
