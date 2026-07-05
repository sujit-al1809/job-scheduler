"""Shared column mixins for models."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, DateTime, Identity, func
from sqlalchemy.orm import Mapped, mapped_column


class PKMixin:
    """Bigint identity primary key.

    Bigints are monotonic and compact: the atomic claim index orders by
    ``(priority DESC, run_at, id)`` and uses ``id`` as the FIFO tiebreaker,
    which only makes sense if ids grow with insertion order — UUIDs would break
    that and bloat the hot index. See docs/design-decisions.md.
    """

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False), primary_key=True
    )


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
