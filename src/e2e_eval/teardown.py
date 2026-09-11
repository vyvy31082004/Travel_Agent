from __future__ import annotations

from psycopg_pool import AsyncConnectionPool

from e2e_eval.seed import e2e_user_prefix
from memory_eval.retrieval_postgres import DELETE_EVAL_EMBEDDINGS_SQL, DELETE_EVAL_MEMORIES_SQL

DELETE_E2E_SEARCH_ITEMS_SQL = """
    DELETE FROM search_result_items
    WHERE search_id IN (
        SELECT search_id FROM search_runs WHERE thread_id = %(thread_id)s
    )
"""

DELETE_E2E_SEARCH_RUNS_SQL = """
    DELETE FROM search_runs WHERE thread_id = %(thread_id)s
"""

DELETE_E2E_MEMORY_JOBS_SQL = """
    DELETE FROM memory_jobs WHERE thread_id = %(thread_id)s
"""

DELETE_E2E_MEMORY_AUDIT_SQL = """
    DELETE FROM memory_audit_records WHERE thread_id = %(thread_id)s
"""

DELETE_E2E_SEARCH_BY_USER_SQL = """
    DELETE FROM search_result_items
    WHERE search_id IN (
        SELECT search_id FROM search_runs WHERE user_id LIKE %(user_prefix)s
    )
"""

DELETE_E2E_SEARCH_RUNS_BY_USER_SQL = """
    DELETE FROM search_runs WHERE user_id LIKE %(user_prefix)s
"""

DELETE_E2E_CHECKPOINT_WRITES_SQL = """
    DELETE FROM checkpoint_writes WHERE thread_id = %(thread_id)s
"""

DELETE_E2E_CHECKPOINT_BLOBS_SQL = """
    DELETE FROM checkpoint_blobs WHERE thread_id = %(thread_id)s
"""

DELETE_E2E_CHECKPOINTS_SQL = """
    DELETE FROM checkpoints WHERE thread_id = %(thread_id)s
"""


async def delete_case_memories(pool: AsyncConnectionPool, case_id: str) -> None:
    params = {"user_prefix": e2e_user_prefix(case_id)}
    async with pool.connection() as conn:
        await conn.execute(DELETE_EVAL_EMBEDDINGS_SQL, params)
        await conn.execute(DELETE_EVAL_MEMORIES_SQL, params)


async def delete_run_artifacts(pool: AsyncConnectionPool, *, thread_id: str) -> None:
    params = {"thread_id": thread_id}
    async with pool.connection() as conn:
        for statement in (
            DELETE_E2E_SEARCH_ITEMS_SQL,
            DELETE_E2E_SEARCH_RUNS_SQL,
            DELETE_E2E_MEMORY_AUDIT_SQL,
            DELETE_E2E_MEMORY_JOBS_SQL,
            DELETE_E2E_CHECKPOINT_WRITES_SQL,
            DELETE_E2E_CHECKPOINT_BLOBS_SQL,
            DELETE_E2E_CHECKPOINTS_SQL,
        ):
            try:
                await conn.execute(statement, params)
            except Exception:
                # LangGraph checkpoint table names may differ by version.
                continue


async def delete_case_artifacts(pool: AsyncConnectionPool, case_id: str) -> None:
    """Remove result-store rows for all runs of an E2E case user prefix."""
    params = {"user_prefix": e2e_user_prefix(case_id)}
    async with pool.connection() as conn:
        for statement in (
            DELETE_E2E_SEARCH_BY_USER_SQL,
            DELETE_E2E_SEARCH_RUNS_BY_USER_SQL,
        ):
            try:
                await conn.execute(statement, params)
            except Exception:
                continue


async def teardown_case_run(
    pool: AsyncConnectionPool,
    *,
    case_id: str,
    thread_id: str,
) -> None:
    await delete_run_artifacts(pool, thread_id=thread_id)
    await delete_case_artifacts(pool, case_id)
    await delete_case_memories(pool, case_id)
