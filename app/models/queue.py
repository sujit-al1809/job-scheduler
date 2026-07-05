"""Queues and their retry policies."""
from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import PKMixin, TimestampMixin
from app.models.enums import RetryStrategy


class RetryPolicy(PKMixin, TimestampMixin, Base):
    __tablename__ = "retry_policies"

    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    strategy: Mapped[RetryStrategy] = mapped_column(
        Enum(RetryStrategy, name="retry_strategy"),
        nullable=False,
        default=RetryStrategy.exponential,
    )
    base_delay_s: Mapped[float] = mapped_column(Float, nullable=False, default=5.0)
    max_delay_s: Mapped[float] = mapped_column(Float, nullable=False, default=3600.0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    jitter: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        CheckConstraint("max_attempts >= 1", name="ck_retry_max_attempts"),
        CheckConstraint("base_delay_s >= 0", name="ck_retry_base_delay"),
    )


class Queue(PKMixin, TimestampMixin, Base):
    __tablename__ = "queues"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_queue_name"),
        CheckConstraint("concurrency_limit >= 1", name="ck_queue_concurrency"),
    )

    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    concurrency_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    is_paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    retry_policy_id: Mapped[int | None] = mapped_column(
        ForeignKey("retry_policies.id", ondelete="SET NULL"), nullable=True, index=True
    )

    project: Mapped["Project"] = relationship(back_populates="queues")  # noqa: F821
    retry_policy: Mapped["RetryPolicy | None"] = relationship()
    jobs: Mapped[list["Job"]] = relationship(  # noqa: F821
        back_populates="queue", cascade="all, delete-orphan"
    )
