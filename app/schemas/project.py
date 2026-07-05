"""Project request/response schemas."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    org_id: int
    name: str
    api_key: str
    created_at: dt.datetime
    updated_at: dt.datetime
