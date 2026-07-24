from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

from settings import Settings


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


@dataclass(frozen=True)
class PostgresResources:
    pool: AsyncConnectionPool
    checkpointer: AsyncPostgresSaver


def create_pool(settings: Settings) -> AsyncConnectionPool:
    return AsyncConnectionPool(
        conninfo=settings.database_url,
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
        timeout=settings.db_pool_timeout_seconds,
        open=False,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
        },
    )


@asynccontextmanager
async def open_postgres(
    settings: Settings,
) -> AsyncIterator[PostgresResources]:
    pool = create_pool(settings)
    try:
        await pool.open(wait=True)
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()
        yield PostgresResources(pool=pool, checkpointer=checkpointer)
    finally:
        await pool.close()
