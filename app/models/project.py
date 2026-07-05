"""Projects — the org-owned unit that groups queues and jobs."""
from __future__ import annotations

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import PKMixin, TimestampMixin


class Project(PKMixin, TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_project_name"),)

    org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    api_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)

    organization: Mapped["Organization"] = relationship(  # noqa: F821
        back_populates="projects"
    )
    queues: Mapped[list["Queue"]] = relationship(  # noqa: F821
        back_populates="project", cascade="all, delete-orphan"
    )
