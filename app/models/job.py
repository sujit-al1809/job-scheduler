"""Jobs, their execution attempts, and log lines — the core of the queue."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import PKMixin, TimestampMixin
from app.models.enums import ExecutionStatus, JobStatus


class Job(PKMixin, TimestampMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        # The atomic-claim index. Partial (only queued rows) keeps it tiny and hot.
        # Column order mirrors the claim ORDER BY: priority DESC, run_at ASC, id ASC.
        Index(
            "ix_jobs_claim",
            "queue_id",
            text("priority DESC"),
            "run_at",
            "id",
            postgresql_where=text("status = 'queued'"),
        ),
        # Per-queue status counts for stats endpoints.
        Index("ix_jobs_queue_status", "queue_id", "status"),
        # Scheduler promotion scan: due 'scheduled' jobs.
        Index(
            "ix_jobs_scheduled_run_at",
            "run_at",
            postgresql_where=text("status = 'scheduled'"),
        ),
        # Client idempotency: at most one live job per (project, key).
        Index(
            "ix_jobs_idempotency",
            "project_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        # Project-scoped listing with date-range filters.
        Index("ix_jobs_project_created", "project_id", "created_at"),
    )

    queue_id: Mapped[int] = mapped_column(
        ForeignKey("queues.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status"),
        nullable=False,
        default=JobStatus.queued,
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    run_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)

    worker_id: Mapped[int | None] = mapped_column(
        ForeignKey("workers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    retry_policy_id: Mapped[int | None] = mapped_column(
        ForeignKey("retry_policies.id", ondelete="SET NULL"), nullable=True
    )

    claimed_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    queue: Mapped["Queue"] = relationship(back_populates="jobs")  # noqa: F821
    executions: Mapped[list["JobExecution"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    logs: Mapped[list["JobLog"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class JobExecution(PKMixin, Base):
    __tablename__ = "job_executions"
    __table_args__ = (
        UniqueConstraint("job_id", "attempt", name="uq_execution_attempt"),
        Index("ix_executions_job_attempt", "job_id", "attempt"),
        # Metrics buckets scan executions by start time.
        Index("ix_executions_started_at", "started_at"),
    )

    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    worker_id: Mapped[int | None] = mapped_column(
        ForeignKey("workers.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[ExecutionStatus] = mapped_column(
        Enum(ExecutionStatus, name="execution_status"),
        nullable=False,
        default=ExecutionStatus.running,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    job: Mapped["Job"] = relationship(back_populates="executions")
    logs: Mapped[list["JobLog"]] = relationship(back_populates="execution")


class JobLog(PKMixin, Base):
    __tablename__ = "job_logs"
    __table_args__ = (Index("ix_job_logs_job_created", "job_id", "created_at"),)

    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    execution_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_executions.id", ondelete="CASCADE"), nullable=True
    )
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    job: Mapped["Job"] = relationship(back_populates="logs")
    execution: Mapped["JobExecution | None"] = relationship(back_populates="logs")
