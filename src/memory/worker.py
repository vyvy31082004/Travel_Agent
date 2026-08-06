from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from psycopg_pool import AsyncConnectionPool

from memory.commit import MemoryCommitAdapter
from memory.consolidation import (
    MemoryCandidateExtractor,
    build_candidate_extractor,
    calculate_transition,
)
from memory.long_term import MemoryFamily
from repositories.long_term_memory import MemorySearchFilters, PostgresLongTermMemoryRepository
from settings import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkerResult:
    processed: bool
    job_id: str | None = None
    status: str = "idle"
    candidates: int = 0
    error: str | None = None


class MemoryWorker:
    def __init__(
        self,
        *,
        pool: AsyncConnectionPool,
        settings: Settings,
        repository: PostgresLongTermMemoryRepository,
        commit_adapter: MemoryCommitAdapter,
        extractor: MemoryCandidateExtractor | None = None,
    ) -> None:
        self._pool = pool
        self._settings = settings
        self._repository = repository
        self._commit_adapter = commit_adapter
        self._extractor = extractor or build_candidate_extractor(settings)

    async def process_next(self) -> WorkerResult:
        job = await self._claim_next_job()
        if not job:
            return WorkerResult(processed=False)
        job_id = str(job["job_id"])
        try:
            candidates = await self._extractor.extract(
                job.get("messages") or [],
                user_id=str(job["user_id"]),
                thread_id=str(job["thread_id"]),
            )
            if not candidates:
                await self._mark_job(job_id, "skipped")
                logger.info("memory job skipped", extra={"job_id": job_id})
                return WorkerResult(
                    processed=True, job_id=job_id, status="skipped", candidates=0
                )

            existing = await self._repository.search_active_memories(
                MemorySearchFilters(
                    user_id=str(job["user_id"]),
                    families=tuple(MemoryFamily),
                    query=None,
                    limit=self._settings.long_term_memory_text_search_limit,
                )
            )
            for candidate in candidates:
                transition = calculate_transition(candidate, existing)
                result = await self._commit_adapter.verify_and_commit(
                    transition=transition,
                    user_id=str(job["user_id"]),
                    thread_id=str(job["thread_id"]),
                    job_id=job_id,
                )
                logger.info(
                    "memory transition processed",
                    extra={
                        "job_id": job_id,
                        "decision": result.decision,
                        "affected_memory_ids": result.affected_memory_ids,
                    },
                )
            await self._mark_job(job_id, "completed")
            return WorkerResult(
                processed=True,
                job_id=job_id,
                status="completed",
                candidates=len(candidates),
            )
        except Exception as exc:
            await self._mark_job_failed(job_id, str(exc))
            logger.warning(
                "memory job failed", extra={"job_id": job_id, "error": str(exc)}
            )
            return WorkerResult(
                processed=True, job_id=job_id, status="failed", error=str(exc)
            )

    async def _claim_next_job(self) -> dict[str, Any] | None:
        async with self._pool.connection() as conn:
            row = await (
                await conn.execute(
                    """
                    UPDATE memory_jobs
                    SET status = 'processing', locked_at = now(),
                        attempts = attempts + 1, updated_at = now()
                    WHERE job_id = (
                        SELECT job_id
                        FROM memory_jobs
                        WHERE status = 'pending'
                          AND attempts < %(retry_limit)s
                        ORDER BY created_at ASC
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    RETURNING job_id, user_id, thread_id, messages, attempts
                    """,
                    {"retry_limit": self._settings.long_term_memory_worker_retry_limit},
                )
            ).fetchone()
        return dict(row) if row else None

    async def _mark_job(self, job_id: str, status: str) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                """
                UPDATE memory_jobs
                SET status = %(status)s, updated_at = now(), error_summary = NULL
                WHERE job_id = %(job_id)s
                """,
                {"job_id": UUID(str(job_id)), "status": status},
            )

    async def _mark_job_failed(self, job_id: str, error_summary: str) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                """
                UPDATE memory_jobs
                SET status = CASE
                        WHEN attempts >= %(retry_limit)s THEN 'failed'
                        ELSE 'pending'
                    END,
                    updated_at = now(),
                    error_summary = %(error_summary)s
                WHERE job_id = %(job_id)s
                """,
                {
                    "job_id": UUID(str(job_id)),
                    "retry_limit": self._settings.long_term_memory_worker_retry_limit,
                    "error_summary": error_summary[:1000],
                },
            )
