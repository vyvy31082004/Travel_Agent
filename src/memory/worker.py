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
from memory.embeddings import MemoryEmbeddingService
from memory.long_term import MemoryFamily
from memory.transition import (
    RelationJudge,
    ScopeJudge,
    build_transition_judges,
    propose_transition,
)
from memory.verifier import MemoryVerifierContext, project_memory_state
from repositories.long_term_memory import (
    LongTermMemoryRepository,
    MemorySearchFilters,
    PostgresLongTermMemoryRepository,
)
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
        embedding_service: MemoryEmbeddingService | None = None,
        scope_judge: ScopeJudge | None = None,
        relation_judge: RelationJudge | None = None,
    ) -> None:
        self._pool = pool
        self._settings = settings
        self._repository: LongTermMemoryRepository = repository
        self._commit_adapter = commit_adapter
        self._extractor = extractor or build_candidate_extractor(settings)
        self._embedding_service = embedding_service
        if scope_judge is not None and relation_judge is not None:
            self._scope_judge = scope_judge
            self._relation_judge = relation_judge
        else:
            built_scope, built_relation = build_transition_judges(settings)
            self._scope_judge = scope_judge or built_scope
            self._relation_judge = relation_judge or built_relation

    async def process_next(self) -> WorkerResult:
        job = await self._claim_next_job()
        if not job:
            return WorkerResult(processed=False)
        return await self._process_claimed_job(job)

    async def process_job(self, job_id: str) -> None:
        """Process a specific memory job (used for sync_finalize).

        Retries while the job remains ``pending`` so sync callers observe a
        terminal status (``completed`` / ``skipped`` / ``failed``).
        """
        max_attempts = max(1, int(self._settings.long_term_memory_worker_retry_limit))
        for _ in range(max_attempts):
            job = await self._claim_job(job_id)
            if not job:
                print(f"[Worker] process_job: could not claim job {job_id}")
                return
            res = await self._process_claimed_job(job)
            print(f"[Worker] process_job result: {res}")
            if res.error:
                print(f"[Worker] error details: {res.error}")
            if res.status != "failed":
                return
        print(f"[Worker] process_job exhausted retries for job {job_id}")

    async def _load_existing(self, user_id: str):
        return await self._repository.search_active_memories(
            MemorySearchFilters(
                user_id=user_id,
                families=tuple(MemoryFamily),
                query=None,
                limit=self._settings.long_term_memory_text_search_limit,
            )
        )

    async def _decide_transition(self, candidate, existing):
        path = self._settings.long_term_memory_transition_path
        if path == "lexical":
            return calculate_transition(candidate, existing)
        return await propose_transition(
            candidate,
            repository=self._repository,
            scope_judge=self._scope_judge,
            relation_judge=self._relation_judge,
            embedder=self._embedding_service,
            confidence_threshold=(
                self._settings.long_term_memory_transition_confidence_threshold
            ),
            batch_size=self._settings.long_term_memory_transition_batch_size,
        )

    async def _process_claimed_job(self, job: dict[str, Any]) -> WorkerResult:
        job_id = str(job["job_id"])
        try:
            user_id = str(job["user_id"])
            existing = await self._load_existing(user_id)

            candidates = await self._extractor.extract(
                job.get("messages") or [],
                user_id=user_id,
                thread_id=str(job["thread_id"]),
                existing_active=existing,
            )
            if not candidates:
                await self._mark_job(job_id, "skipped")
                logger.info("memory job skipped", extra={"job_id": job_id})
                return WorkerResult(
                    processed=True, job_id=job_id, status="skipped", candidates=0
                )

            for candidate in candidates:
                transition = await self._decide_transition(candidate, existing)
                result = await self._commit_adapter.verify_and_commit(
                    transition=transition,
                    user_id=user_id,
                    thread_id=str(job["thread_id"]),
                    job_id=job_id,
                    verifier_context=MemoryVerifierContext(
                        chunk=tuple(job.get("messages") or ()),
                        old_memories=tuple(existing),
                        new_memories=tuple(project_memory_state(transition, existing)),
                    ),
                )
                logger.info(
                    "memory transition processed",
                    extra={
                        "job_id": job_id,
                        "decision": result.decision,
                        "affected_memory_ids": result.affected_memory_ids,
                    },
                )
                if result.decision in {"approve", "noop"} and result.affected_memory_ids:
                    existing = await self._load_existing(user_id)
            await self._mark_job(job_id, "completed")
            return WorkerResult(
                processed=True,
                job_id=job_id,
                status="completed",
                candidates=len(candidates),
            )
        except Exception as exc:
            error_text = repr(exc)
            await self._mark_job_failed(job_id, error_text)
            logger.exception("memory job failed job_id=%s", job_id)
            print(f"[Worker] memory job failed job_id={job_id}: {error_text}")
            return WorkerResult(
                processed=True, job_id=job_id, status="failed", error=error_text
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

    async def _claim_job(self, job_id: str) -> dict[str, Any] | None:
        async with self._pool.connection() as conn:
            row = await (
                await conn.execute(
                    """
                    UPDATE memory_jobs
                    SET status = 'processing', locked_at = now(),
                        attempts = attempts + 1, updated_at = now()
                    WHERE job_id = %(job_id)s
                      AND status = 'pending'
                      AND attempts < %(retry_limit)s
                    RETURNING job_id, user_id, thread_id, messages, attempts
                    """,
                    {
                        "job_id": UUID(str(job_id)),
                        "retry_limit": self._settings.long_term_memory_worker_retry_limit,
                    },
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
