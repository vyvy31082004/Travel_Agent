from typing import Any

from fastapi import Request
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

from settings import Settings


def get_database_pool(request: Request) -> AsyncConnectionPool:
    return request.app.state.database_pool


def get_checkpointer(request: Request) -> AsyncPostgresSaver:
    return request.app.state.checkpointer


def get_primary_graph(request: Request) -> Any:
    return request.app.state.primary_graph


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings
