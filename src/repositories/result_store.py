from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Sequence
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)


class ResultStoreError(Exception):
    """Base Result Store error."""


class ResultStoreNotFoundError(ResultStoreError):
    """Requested search/item was not found or not owned by caller."""


class ResultStoreExpiredError(ResultStoreError):
    """Requested search/item exists but TTL has expired."""


@dataclass
class StoredSearchRef:
    search_id: str
    request_id: str
    domain: str
    total_results: int
    displayed_item_ids: list[str]
    expires_at: datetime


class ResultStoreRepository:
    def __init__(
        self,
        pool: AsyncConnectionPool,
        default_ttl: timedelta | None = None,
        domain_ttls: dict[str, timedelta] | None = None,
    ) -> None:
        self._pool = pool
        self._default_ttl = default_ttl or timedelta(hours=6)
        self._domain_ttls = domain_ttls or {
            "flight": timedelta(hours=2),
            "hotel": timedelta(hours=12),
            "tour": timedelta(hours=12),
            "car": timedelta(hours=6),
        }

    def _ttl_for(self, domain: str) -> timedelta:
        return self._domain_ttls.get(domain, self._default_ttl)

    @staticmethod
    def _row_to_item(row: dict[str, Any] | Any) -> dict[str, Any]:
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            payload = {"value": payload}
        item = dict(payload)
        item["item_id"] = row["item_id"]
        item["position"] = row["position"]
        if "api_position" in row:
            item["api_position"] = row["api_position"]
        if "eligible" in row:
            item["eligible"] = row["eligible"]
        return item

    async def save_search(
        self,
        *,
        user_id: str,
        thread_id: str,
        request_id: str,
        domain: str,
        query: dict[str, Any],
        items: Sequence[dict[str, Any]],
        status: str = "completed",
        display_limit: int = 10,
        ttl: timedelta | None = None,
    ) -> StoredSearchRef:
        if not user_id or not thread_id or not request_id:
            raise ResultStoreError("user_id, thread_id, and request_id are required")

        search_id = uuid4()
        now = datetime.now(timezone.utc)
        expires_at = now + (ttl or self._ttl_for(domain))
        prepared_items = list(items)

        async with self._pool.connection() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO search_runs (
                        search_id, user_id, thread_id, request_id, domain,
                        query, status, total_results, expires_at
                    ) VALUES (
                        %(search_id)s, %(user_id)s, %(thread_id)s, %(request_id)s,
                        %(domain)s, %(query)s, %(status)s, %(total_results)s,
                        %(expires_at)s
                    )
                    """,
                    {
                        "search_id": search_id,
                        "user_id": str(user_id),
                        "thread_id": str(thread_id),
                        "request_id": str(request_id),
                        "domain": domain,
                        "query": Jsonb(query or {}),
                        "status": status,
                        "total_results": len(prepared_items),
                        "expires_at": expires_at,
                    },
                )

                for api_position, item in enumerate(prepared_items, start=1):
                    item_id = str(item.get("item_id") or f"{domain}_{api_position}")
                    payload = dict(item.get("payload") or item)
                    payload.setdefault("item_id", item_id)
                    if item.get("detail_token") is not None:
                        payload["detail_token"] = item["detail_token"]
                    await conn.execute(
                        """
                        INSERT INTO search_result_items (
                            search_id, item_id, api_position, position,
                            eligible, payload
                        ) VALUES (
                            %(search_id)s, %(item_id)s, %(api_position)s,
                            %(position)s, %(eligible)s, %(payload)s
                        )
                        """,
                        {
                            "search_id": search_id,
                            "item_id": item_id,
                            "api_position": api_position,
                            "position": api_position,
                            "eligible": None,
                            "payload": Jsonb(payload),
                        },
                    )

        displayed = [
            str(item.get("item_id") or f"{domain}_{idx}")
            for idx, item in enumerate(prepared_items[:display_limit], start=1)
        ]
        return StoredSearchRef(
            search_id=str(search_id),
            request_id=str(request_id),
            domain=domain,
            total_results=len(prepared_items),
            displayed_item_ids=displayed,
            expires_at=expires_at,
        )

    async def _get_owned_search(
        self,
        conn,
        *,
        search_id: str,
        user_id: str,
        thread_id: str,
        allow_expired: bool = False,
    ) -> dict[str, Any]:
        row = await (
            await conn.execute(
                """
                SELECT search_id, user_id, thread_id, request_id, domain,
                       query, status, total_results, expires_at, created_at
                FROM search_runs
                WHERE search_id = %(search_id)s
                  AND user_id = %(user_id)s
                  AND thread_id = %(thread_id)s
                """,
                {
                    "search_id": UUID(str(search_id)),
                    "user_id": str(user_id),
                    "thread_id": str(thread_id),
                },
            )
        ).fetchone()
        if not row:
            raise ResultStoreNotFoundError(
                "Search not found for the given user/thread ownership"
            )

        search = dict(row)
        expires_at = search["expires_at"]
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
            search["expires_at"] = expires_at
        if (
            not allow_expired
            and expires_at is not None
            and expires_at < datetime.now(timezone.utc)
        ):
            raise ResultStoreExpiredError(
                f"Search {search_id} expired at {expires_at.isoformat()}"
            )
        return search

    async def load_search(
        self,
        *,
        search_id: str,
        user_id: str,
        thread_id: str,
        allow_expired: bool = False,
    ) -> dict[str, Any]:
        async with self._pool.connection() as conn:
            return await self._get_owned_search(
                conn,
                search_id=search_id,
                user_id=user_id,
                thread_id=thread_id,
                allow_expired=allow_expired,
            )

    async def list_all_items(
        self,
        *,
        search_id: str,
        user_id: str,
        thread_id: str,
        allow_expired: bool = False,
    ) -> list[dict[str, Any]]:
        async with self._pool.connection() as conn:
            await self._get_owned_search(
                conn,
                search_id=search_id,
                user_id=user_id,
                thread_id=thread_id,
                allow_expired=allow_expired,
            )
            rows = await (
                await conn.execute(
                    """
                    SELECT item_id, api_position, position, eligible, payload
                    FROM search_result_items
                    WHERE search_id = %(search_id)s
                    ORDER BY api_position ASC
                    """,
                    {"search_id": UUID(str(search_id))},
                )
            ).fetchall()
        return [self._row_to_item(row) for row in rows]

    async def list_item_ids(
        self,
        *,
        search_id: str,
        user_id: str,
        thread_id: str,
        allow_expired: bool = False,
    ) -> list[str]:
        items = await self.list_all_items(
            search_id=search_id,
            user_id=user_id,
            thread_id=thread_id,
            allow_expired=allow_expired,
        )
        return [str(item["item_id"]) for item in items if item.get("item_id")]

    async def has_display_decisions(
        self,
        *,
        search_id: str,
        user_id: str,
        thread_id: str,
        allow_expired: bool = False,
    ) -> bool:
        async with self._pool.connection() as conn:
            await self._get_owned_search(
                conn,
                search_id=search_id,
                user_id=user_id,
                thread_id=thread_id,
                allow_expired=allow_expired,
            )
            row = await (
                await conn.execute(
                    """
                    SELECT 1
                    FROM search_result_items
                    WHERE search_id = %(search_id)s
                      AND eligible IS NOT NULL
                    LIMIT 1
                    """,
                    {"search_id": UUID(str(search_id))},
                )
            ).fetchone()
        return row is not None

    async def update_display_decisions(
        self,
        *,
        search_id: str,
        presented_item_ids: Sequence[str],
        user_id: str,
        thread_id: str,
    ) -> list[str]:
        if not presented_item_ids:
            return []

        async with self._pool.connection() as conn:
            async with conn.transaction():
                await self._get_owned_search(
                    conn,
                    search_id=search_id,
                    user_id=user_id,
                    thread_id=thread_id,
                )
                await conn.execute(
                    """
                    UPDATE search_result_items
                    SET position = NULL, eligible = false
                    WHERE search_id = %(search_id)s
                    """,
                    {"search_id": UUID(str(search_id))},
                )
                for display_position, item_id in enumerate(presented_item_ids, start=1):
                    await conn.execute(
                        """
                        UPDATE search_result_items
                        SET eligible = true, position = %(position)s
                        WHERE search_id = %(search_id)s
                          AND item_id = %(item_id)s
                        """,
                        {
                            "search_id": UUID(str(search_id)),
                            "item_id": str(item_id),
                            "position": display_position,
                        },
                    )

        return await self.load_displayed_item_ids(
            search_id=search_id,
            user_id=user_id,
            thread_id=thread_id,
        )

    async def load_displayed_item_ids(
        self,
        *,
        search_id: str,
        user_id: str,
        thread_id: str,
        allow_expired: bool = False,
    ) -> list[str]:
        async with self._pool.connection() as conn:
            await self._get_owned_search(
                conn,
                search_id=search_id,
                user_id=user_id,
                thread_id=thread_id,
                allow_expired=allow_expired,
            )
            rows = await (
                await conn.execute(
                    """
                    SELECT item_id
                    FROM search_result_items
                    WHERE search_id = %(search_id)s
                      AND eligible = true
                      AND position IS NOT NULL
                    ORDER BY position ASC
                    """,
                    {"search_id": UUID(str(search_id))},
                )
            ).fetchall()
        return [str(row["item_id"]) for row in rows]

    async def load_displayed_items(
        self,
        *,
        search_id: str,
        user_id: str,
        thread_id: str,
        allow_expired: bool = False,
        include_detail_token: bool = False,
    ) -> list[dict[str, Any]]:
        item_ids = await self.load_displayed_item_ids(
            search_id=search_id,
            user_id=user_id,
            thread_id=thread_id,
            allow_expired=allow_expired,
        )
        if not item_ids:
            return []
        items = await self.load_items(
            search_id=search_id,
            item_ids=item_ids,
            user_id=user_id,
            thread_id=thread_id,
            allow_expired=allow_expired,
        )
        if not include_detail_token:
            for item in items:
                item.pop("detail_token", None)
        return items

    async def load_items(
        self,
        *,
        search_id: str,
        item_ids: Sequence[str],
        user_id: str,
        thread_id: str,
        allow_expired: bool = False,
    ) -> list[dict[str, Any]]:
        async with self._pool.connection() as conn:
            await self._get_owned_search(
                conn,
                search_id=search_id,
                user_id=user_id,
                thread_id=thread_id,
                allow_expired=allow_expired,
            )
            rows = await (
                await conn.execute(
                    """
                    SELECT item_id, api_position, position, eligible, payload
                    FROM search_result_items
                    WHERE search_id = %(search_id)s
                      AND item_id = ANY(%(item_ids)s)
                    ORDER BY position ASC NULLS LAST, api_position ASC
                    """,
                    {
                        "search_id": UUID(str(search_id)),
                        "item_ids": list(item_ids),
                    },
                )
            ).fetchall()

        found = {row["item_id"]: row for row in rows}
        ordered: list[dict[str, Any]] = []
        for item_id in item_ids:
            row = found.get(item_id)
            if not row:
                continue
            ordered.append(self._row_to_item(row))
        return ordered

    async def load_item(
        self,
        *,
        search_id: str,
        item_id: str,
        user_id: str,
        thread_id: str,
        allow_expired: bool = False,
        include_detail_token: bool = False,
    ) -> dict[str, Any]:
        items = await self.load_items(
            search_id=search_id,
            item_ids=[item_id],
            user_id=user_id,
            thread_id=thread_id,
            allow_expired=allow_expired,
        )
        if not items:
            raise ResultStoreNotFoundError(
                f"Item {item_id} not found in search {search_id}"
            )
        item = items[0]
        if not include_detail_token:
            item.pop("detail_token", None)
        return item

    async def load_items_by_positions(
        self,
        *,
        search_id: str,
        positions: Sequence[int],
        user_id: str,
        thread_id: str,
        allow_expired: bool = False,
        displayed_only: bool = True,
    ) -> list[dict[str, Any]]:
        position_list = list(positions)
        async with self._pool.connection() as conn:
            await self._get_owned_search(
                conn,
                search_id=search_id,
                user_id=user_id,
                thread_id=thread_id,
                allow_expired=allow_expired,
            )
            has_decisions = False
            decision_row = await (
                await conn.execute(
                    """
                    SELECT 1
                    FROM search_result_items
                    WHERE search_id = %(search_id)s
                      AND eligible IS NOT NULL
                    LIMIT 1
                    """,
                    {"search_id": UUID(str(search_id))},
                )
            ).fetchone()
            has_decisions = decision_row is not None
            eligible_clause = "AND eligible = true" if displayed_only and has_decisions else ""
            rows = await (
                await conn.execute(
                    f"""
                    SELECT item_id, api_position, position, eligible, payload
                    FROM search_result_items
                    WHERE search_id = %(search_id)s
                      AND position = ANY(%(positions)s)
                      {eligible_clause}
                    ORDER BY position ASC
                    """,
                    {
                        "search_id": UUID(str(search_id)),
                        "positions": position_list,
                    },
                )
            ).fetchall()

        return [self._row_to_item(row) for row in rows]

    async def is_expired(
        self, *, search_id: str, user_id: str, thread_id: str
    ) -> bool:
        try:
            async with self._pool.connection() as conn:
                await self._get_owned_search(
                    conn,
                    search_id=search_id,
                    user_id=user_id,
                    thread_id=thread_id,
                    allow_expired=False,
                )
            return False
        except ResultStoreExpiredError:
            return True
