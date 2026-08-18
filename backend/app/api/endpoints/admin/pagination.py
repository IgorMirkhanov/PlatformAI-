"""Shared pagination helpers for Admin Panel list endpoints."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel, Field

T = TypeVar("T")


class AdminPaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total_pages: int = Field(ge=0)


def clamp_page(page: int) -> int:
    return max(1, int(page or 1))


def clamp_page_size(page_size: int, *, default: int = 20, maximum: int = 100) -> int:
    size = int(page_size or default)
    return max(1, min(maximum, size))


def total_pages(total: int, page_size: int) -> int:
    if total <= 0 or page_size <= 0:
        return 0
    return int(math.ceil(total / page_size))


def page_offset(page: int, page_size: int) -> int:
    return (clamp_page(page) - 1) * page_size


def build_paginated(
    items: list[Any],
    *,
    total: int,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    safe_page = clamp_page(page)
    safe_size = clamp_page_size(page_size)
    return {
        "items": items,
        "total": int(total),
        "page": safe_page,
        "page_size": safe_size,
        "total_pages": total_pages(int(total), safe_size),
    }


class PaginationParams:
    """FastAPI dependency for common list query params."""

    def __init__(
        self,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=100),
        search: str = Query(default="", max_length=255),
        status: str | None = Query(default=None, max_length=64),
        date_from: datetime | None = Query(default=None),
        date_to: datetime | None = Query(default=None),
    ) -> None:
        self.page = clamp_page(page)
        self.page_size = clamp_page_size(page_size)
        self.search = (search or "").strip()
        self.status = (status or "").strip() or None
        self.date_from = date_from
        self.date_to = date_to
        self.offset = page_offset(self.page, self.page_size)
