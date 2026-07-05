"""Recurring job templates (cron), materialized into jobs by the scheduler."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import PKMixin, TimestampMixin


class ScheduledJob(PKMixin, TimestampMixin, Base):
    __tablename__ = "scheduled_jobs"
    __table_args__ = (
        # Scheduler scans for due, active templates.
        Index(
            "ix_scheduled_next_run",
            "next_run_at",
            postgresql_where=text("is_active = true"),
        ),
    )

    queue_id: Mapped[int] = mapped_column(
        ForeignKey("queues.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    type: Mapped[str] = mapped_column(String(255), nullable=False)
    cron_expr: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    priority: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_run_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    queue: Mapped["Queue"] = relationship()  # noqa: F821
