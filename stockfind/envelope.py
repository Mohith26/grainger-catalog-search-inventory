"""Consistent API response envelope + bounded pagination metadata.

Every endpoint returns the same shape: ``{success, data, error, meta}``. This is
the single place that shape is defined, so responses never drift between routes.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class PageMeta(BaseModel):
    total: int
    limit: int
    offset: int
    returned: int


def ok(data: Any, meta: PageMeta | None = None) -> dict[str, Any]:
    return {"success": True, "data": data, "error": None, "meta": _meta_dict(meta)}


def fail(error: str) -> dict[str, Any]:
    return {"success": False, "data": None, "error": error, "meta": None}


def _meta_dict(meta: PageMeta | None) -> dict[str, Any] | None:
    return meta.model_dump() if meta is not None else None
