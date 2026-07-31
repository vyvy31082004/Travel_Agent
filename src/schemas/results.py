from __future__ import annotations

from typing import Any, Optional, TypedDict


class CompactSearchRef(TypedDict, total=False):
    request_id: str
    search_id: str
    domain: str
    total_results: int
    displayed_item_ids: list[str]
    labels: list[dict[str, Any]]


class VisibleResultRef(TypedDict, total=False):
    search_id: str
    displayed_item_ids: list[str]
    domain: str


class RequestMeta(TypedDict, total=False):
    domain: str
    status: str
    parameters: dict[str, Any]


class NormalizedResultItem(TypedDict, total=False):
    item_id: str
    detail_token: Optional[str]
    payload: dict[str, Any]
