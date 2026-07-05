"""Shared schema building blocks."""
from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Standard list envelope: {items, total, limit, offset}."""

    items: list[T]
    total: int
    limit: int
    offset: int
