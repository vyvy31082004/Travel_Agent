from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from psycopg_pool import AsyncConnectionPool


@dataclass(frozen=True)
class ConversationRef:
    thread_id: str
    title: str | None
    preview: str | None
    updated_at: datetime


def _preview_from_text(text: str, *, limit: int = 120) -> str:
    text = " ".join((text or "").split())
    return text[:limit]


class ConversationsRepository:
    """Maps chat threads to their owning user for listing and reopening.

    Message content itself is stored by the LangGraph checkpointer (keyed by
    thread_id); this repository only records ownership + display metadata.
    """

    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def upsert(
        self,
        *,
        thread_id: str,
        user_id: str,
        title: str | None = None,
        preview: str | None = None,
    ) -> None:
        thread = (thread_id or "").strip()
        if not thread or not user_id:
            return
        title_val = _preview_from_text(title, limit=80) if title else None
        preview_val = _preview_from_text(preview) if preview else None
        async with self._pool.connection() as conn:
            await conn.execute(
                """
                INSERT INTO conversations (thread_id, user_id, title, preview)
                VALUES (%(thread_id)s, %(user_id)s, %(title)s, %(preview)s)
                ON CONFLICT (thread_id) DO UPDATE SET
                    preview = COALESCE(EXCLUDED.preview, conversations.preview),
                    title = COALESCE(conversations.title, EXCLUDED.title),
                    updated_at = now()
                WHERE conversations.user_id = EXCLUDED.user_id
                """,
                {
                    "thread_id": thread,
                    "user_id": UUID(str(user_id)),
                    "title": title_val,
                    "preview": preview_val,
                },
            )

    async def list_by_user(
        self, user_id: str, *, limit: int = 50
    ) -> list[ConversationRef]:
        if not user_id:
            return []
        async with self._pool.connection() as conn:
            rows = await (
                await conn.execute(
                    """
                    SELECT thread_id, title, preview, updated_at
                    FROM conversations
                    WHERE user_id = %(user_id)s
                    ORDER BY updated_at DESC
                    LIMIT %(limit)s
                    """,
                    {"user_id": UUID(str(user_id)), "limit": limit},
                )
            ).fetchall()
        return [
            ConversationRef(
                thread_id=row["thread_id"],
                title=row["title"],
                preview=row["preview"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    async def get_owner(self, thread_id: str) -> str | None:
        thread = (thread_id or "").strip()
        if not thread:
            return None
        async with self._pool.connection() as conn:
            row = await (
                await conn.execute(
                    "SELECT user_id FROM conversations WHERE thread_id = %(thread_id)s",
                    {"thread_id": thread},
                )
            ).fetchone()
        return str(row["user_id"]) if row else None
