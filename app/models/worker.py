"""Workers and their heartbeat history."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import PKMixin
from app.models.enums import WorkerStatus


class Worker(PKMixin, Base):
    __tablename__ = "workers"
    __table_args__ = (
        # Reaper scans for workers whose heartbeat has gone stale.
        Index("ix_workers_heartbeat", "last_heartbeat_at"),
        Index("ix_workers_status", "status"),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[WorkerStatus] = mapped_column(
        Enum(WorkerStatus, name="worker_status"),
        nullable=False,
        default=WorkerStatus.online,
    )
    concurrency: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_heartbeat_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    stopped_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    heartbeats: Mapped[list["WorkerHeartbeat"]] = relationship(
        back_populates="worker", cascade="all, delete-orphan"
    )


class WorkerHeartbeat(PKMixin, Base):
    __tablename__ = "worker_heartbeats"
    __table_args__ = (
        Index("ix_heartbeats_worker_created", "worker_id", "created_at"),
    )

    worker_id: Mapped[int] = mapped_column(
        ForeignKey("workers.id", ondelete="CASCADE"), nullable=False
    )
    in_flight: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    worker: Mapped["Worker"] = relationship(back_populates="heartbeats")
