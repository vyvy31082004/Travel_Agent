from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.mark.skipif(
    not os.getenv("RUN_POSTGRES_INTEGRATION"),
    reason="RUN_POSTGRES_INTEGRATION required (real Postgres)",
)
def test_conversations_repository_crud():
    import asyncio
    import selectors

    from infrastructure.postgres import create_pool
    from repositories.conversations import ConversationsRepository
    from services.auth import AuthRepository, hash_password
    from settings import get_settings

    async def _run():
        settings = get_settings()
        pool = create_pool(settings)
        await pool.open(wait=True)
        try:
            auth = AuthRepository(pool)
            repo = ConversationsRepository(pool)
            # a real user is required (FK), create one
            email = f"conv-{uuid.uuid4().hex[:8]}@example.com"
            user = await auth.create_user(
                email=email, full_name="Conv Test", password="password123"
            )
            other = await auth.create_user(
                email=f"other-{uuid.uuid4().hex[:8]}@example.com",
                full_name="Other",
                password="password123",
            )
            t1 = f"conv-t1-{uuid.uuid4().hex[:8]}"
            t2 = f"conv-t2-{uuid.uuid4().hex[:8]}"
            t_other = f"conv-to-{uuid.uuid4().hex[:8]}"

            # insert then update (no duplicate)
            await repo.upsert(thread_id=t1, user_id=user.user_id, title="First", preview="p1")
            await repo.upsert(thread_id=t1, user_id=user.user_id, title=None, preview="p1-updated")
            await repo.upsert(thread_id=t2, user_id=user.user_id, title="Second", preview="p2")
            await repo.upsert(thread_id=t_other, user_id=other.user_id, title="X", preview="x")

            owned = await repo.list_by_user(user.user_id)
            owned_ids = {c.thread_id for c in owned}
            assert owned_ids == {t1, t2}, owned_ids  # only own, no duplicate for t1
            # updated preview retained, title preserved from first insert
            t1_row = next(c for c in owned if c.thread_id == t1)
            assert t1_row.preview == "p1-updated"
            assert t1_row.title == "First"
            # most-recent-first ordering: t2 (or t1) updated last is first
            assert owned[0].updated_at >= owned[-1].updated_at

            # get_owner
            assert await repo.get_owner(t1) == user.user_id
            assert await repo.get_owner(t_other) == other.user_id
            assert await repo.get_owner("does-not-exist") is None

            # cleanup
            async with pool.connection() as conn:
                await conn.execute(
                    "DELETE FROM conversations WHERE thread_id = ANY(%s)",
                    ([t1, t2, t_other],),
                )
                for u in (user.user_id, other.user_id):
                    await conn.execute("DELETE FROM users WHERE user_id = %s", (uuid.UUID(u),))
        finally:
            await pool.close()

    asyncio.run(
        _run(),
        loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
    )
