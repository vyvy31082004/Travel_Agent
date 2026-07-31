import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import app as app_module
from infrastructure.postgres import create_pool
from settings import Settings


def test_settings_reject_invalid_pool_range() -> None:
    with pytest.raises(ValueError, match="DB_POOL_MIN_SIZE"):
        Settings(
            database_url="postgresql://user:pass@localhost/database",
            cookie_secret="test-secret",
            db_pool_min_size=5,
            db_pool_max_size=2,
        )


def test_settings_require_cookie_secret() -> None:
    with pytest.raises(ValueError, match="COOKIE_SECRET"):
        Settings(
            database_url="postgresql://user:pass@localhost/database",
            cookie_secret="",
        )


def test_create_pool_uses_configured_limits() -> None:
    pool = create_pool(
        Settings(
            database_url="postgresql://user:pass@localhost/database",
            cookie_secret="test-secret",
            db_pool_min_size=2,
            db_pool_max_size=7,
            db_pool_timeout_seconds=11,
        )
    )

    stats = pool.get_stats()
    assert stats["pool_min"] == 2
    assert stats["pool_max"] == 7


def test_lifespan_injects_shared_postgres_resources(monkeypatch) -> None:
    settings = object()
    pool = object()
    checkpointer = object()
    expected_checkpointer = checkpointer
    graph = object()

    @asynccontextmanager
    async def fake_open_postgres(received_settings):
        assert received_settings is settings
        yield SimpleNamespace(pool=pool, checkpointer=checkpointer)

    async def fake_build_primary_graph(*, checkpointer, repo=None):
        assert checkpointer is expected_checkpointer
        assert repo is not None
        return graph

    class FakeRepo:
        def __init__(self, pool):
            self.pool = pool

    monkeypatch.setattr(app_module, "get_settings", lambda: settings)
    monkeypatch.setattr(app_module, "open_postgres", fake_open_postgres)
    monkeypatch.setattr(app_module, "build_primary_graph", fake_build_primary_graph)
    monkeypatch.setattr(app_module, "ResultStoreRepository", FakeRepo)

    async def verify_lifespan() -> None:
        async with app_module.lifespan(app_module.app):
            assert app_module.app.state.settings is settings
            assert app_module.app.state.database_pool is pool
            assert app_module.app.state.checkpointer is checkpointer
            assert app_module.app.state.primary_graph is graph
            assert app_module.app.state.result_store.pool is pool

    asyncio.run(verify_lifespan())
