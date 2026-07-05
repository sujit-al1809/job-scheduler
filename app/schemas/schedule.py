"""Recurring-schedule (cron) request/response schemas."""
from __future__ import annotations

import datetime as dt
from typing import Any

from croniter import croniter
from pydantic import BaseModel, ConfigDict, Field, field_validator


def _validate_cron(v: str) -> str:
    if not croniter.is_valid(v):
        raise ValueError("invalid cron expression")
    return v


class ScheduleCreate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    type: str = Field(min_length=1, max_length=255)
    cron_expr: str = Field(min_length=1, max_length=255)
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int | None = None

    @field_validator("cron_expr")
    @classmethod
    def _cron(cls, v: str) -> str:
        return _validate_cron(v)


class ScheduleUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    type: str | None = Field(default=None, min_length=1, max_length=255)
    cron_expr: str | None = Field(default=None, min_length=1, max_length=255)
    payload: dict[str, Any] | None = None
    priority: int | None = None

    @field_validator("cron_expr")
    @classmethod
    def _cron(cls, v: str | None) -> str | None:
        return _validate_cron(v) if v is not None else v


class ScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    queue_id: int
    name: str | None
    type: str
    cron_expr: str
    payload: dict[str, Any]
    priority: int | None
    next_run_at: dt.datetime
    is_active: bool
    created_at: dt.datetime
    updated_at: dt.datetime
