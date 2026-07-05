"""Dead-letter-queue response schemas."""
from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict


class DeadLetterJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    project_id: int
    queue_id: int | None
    type: str
    payload: dict[str, Any]
    final_error: str | None
    attempts: int
    moved_at: dt.datetime
    created_at: dt.datetime
