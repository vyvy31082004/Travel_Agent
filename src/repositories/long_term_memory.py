from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, Sequence
from uuid import UUID, uuid4

from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from memory.embeddings import vector_literal
from memory.long_term import MemoryFamily, TravelMemory
from memory.validity import apply_default_validity_if_missing


@dataclass(frozen=True)
class MemorySearchFilters:
    user_id: str
    families: tuple[MemoryFamily, ...]
    limit: int
    query: str | None = None
    domains: tuple[str, ...] | None = None


def _domain_filter_clause(filters: MemorySearchFilters, params: dict[str, Any]) -> str:
    if not filters.domains:
        return ""
    params["domains"] = [str(domain) for domain in filters.domains]
    return " AND domain = ANY(%(domains)s)"


@dataclass(frozen=True)
class MemoryJobRef:
    job_id: str
    idempotency_key: str
    status: str
    created: bool

@dataclass(frozen=True)
class MemoryEmbeddingRecord:
    memory_id: str
    embedding: Sequence[float]
    embedding_model: str
    embedding_dims: int
    content_hash: str


@dataclass(frozen=True)
class RankedMemory:
    memory: TravelMemory
    distance: float | None = None


class LongTermMemoryRepository(Protocol):
    async def search_active_memories(
        self, filters: MemorySearchFilters
    ) -> list[TravelMemory]:
        """Return active memories matching user/family/query filters."""

    async def fetch_active_domain_memories(
        self,
        *,
        user_id: str,
        domain: str,
        limit: int,
    ) -> list[TravelMemory]:
        """Return active travel-preference memories for one user and domain."""

    async def insert_memory(self, memory: TravelMemory) -> str:
        """Insert an approved memory and return its id."""

    async def upsert_memory_embedding(self, record: MemoryEmbeddingRecord) -> None:
        """Persist the current embedding for an approved memory."""

    async def find_memories_missing_current_embedding(
        self,
        *,
        embedding_model: str,
        embedding_dims: int,
        limit: int,
    ) -> list[TravelMemory]:
        """Return active memories needing a current embedding."""

    async def semantic_search_active_memories(
        self,
        filters: MemorySearchFilters,
        *,
        query_embedding: Sequence[float],
        embedding_model: str,
        embedding_dims: int,
        distance_threshold: float,
    ) -> list[TravelMemory]:
        """Return active memories ranked by pgvector distance."""

    async def fetch_transition_comparison_pool(
        self,
        *,
        user_id: str,
        category: str,
        domain: str,
        candidate_embedding: Sequence[float] | None = None,
        embedding_model: str = "",
        embedding_dims: int = 0,
    ) -> list[RankedMemory]:
        """Return active same category/domain memories ranked for transition."""

    async def mark_memory_superseded(self, memory_id: str) -> None:
        """Mark an active memory as superseded."""

    async def commit_supersede(
        self, *, existing_memory_id: str, new_memory: TravelMemory
    ) -> str:
        """Atomically supersede one memory and insert its replacement."""

    async def write_audit_record(
        self,
        *,
        job_id: str | None,
        user_id: str,
        thread_id: str | None,
        decision: str,
        proposed_transition: dict[str, Any],
        rule_result: dict[str, Any] | None = None,
        verifier_result: dict[str, Any] | None = None,
        affected_memory_ids: Sequence[str] | None = None,
    ) -> None:
        """Persist a memory transition audit record."""

    async def enqueue_memory_job(
        self,
        *,
        user_id: str,
        thread_id: str,
        idempotency_key: str,
        final_message_id: str | None,
        checkpoint_id: str | None,
        messages: Sequence[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> MemoryJobRef:
        """Create or return an idempotent memory consolidation job."""


class PostgresLongTermMemoryRepository:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def search_active_memories(
        self, filters: MemorySearchFilters
    ) -> list[TravelMemory]:
        families = [str(family) for family in filters.families]
        params: dict[str, Any] = {
            "user_id": filters.user_id,
            "families": families,
            "limit": filters.limit,
        }
        query_clause = ""
        if filters.query:
            terms = [term for term in filters.query.split() if len(term) >= 2][:8]
            if terms:
                like_patterns = [f"%{term}%" for term in terms]
                params["patterns"] = like_patterns
                query_clause = """
                  AND (
                    memory_text ILIKE ANY(%(patterns)s)
                    OR COALESCE(condition, '') ILIKE ANY(%(patterns)s)
                    OR evidence_text ILIKE ANY(%(patterns)s)
                  )
                """
        domain_clause = _domain_filter_clause(filters, params)

        async with self._pool.connection() as conn:
            rows = await (
                await conn.execute(
                    f"""
                    SELECT memory_id, user_id, memory_text, category, domain,
                           condition, evidence_text, source_thread_id, status,
                           valid_from, valid_to, supersedes_memory_id,
                           created_at, updated_at, metadata
                    FROM long_term_memories
                    WHERE user_id = %(user_id)s
                      AND family = ANY(%(families)s)
                      AND status = 'active'
                      AND (valid_from IS NULL OR valid_from <= now())
                      AND (valid_to IS NULL OR valid_to > now())
                      {domain_clause}
                      {query_clause}
                    ORDER BY updated_at DESC, created_at DESC
                    LIMIT %(limit)s
                    """,
                    params,
                )
            ).fetchall()
        return [TravelMemory.from_record(dict(row)) for row in rows]

    async def fetch_active_domain_memories(
        self,
        *,
        user_id: str,
        domain: str,
        limit: int,
    ) -> list[TravelMemory]:
        async with self._pool.connection() as conn:
            rows = await (
                await conn.execute(
                    """
                    SELECT memory_id, user_id, memory_text, category, domain,
                           condition, evidence_text, source_thread_id, status,
                           valid_from, valid_to, supersedes_memory_id,
                           created_at, updated_at, metadata
                    FROM long_term_memories
                    WHERE user_id = %(user_id)s
                      AND domain = %(domain)s
                      AND family = %(family)s
                      AND status = 'active'
                      AND (valid_from IS NULL OR valid_from <= now())
                      AND (valid_to IS NULL OR valid_to > now())
                    ORDER BY updated_at DESC, created_at DESC
                    LIMIT %(limit)s
                    """,
                    {
                        "user_id": user_id,
                        "domain": domain,
                        "family": MemoryFamily.TRAVEL_PREFERENCES.value,
                        "limit": limit,
                    },
                )
            ).fetchall()
        return [TravelMemory.from_record(dict(row)) for row in rows]

    async def insert_memory(self, memory: TravelMemory) -> str:
        memory_id = uuid4()
        record = apply_default_validity_if_missing(memory).to_record()
        async with self._pool.connection() as conn:
            await conn.execute(
                """
                INSERT INTO long_term_memories (
                    memory_id, user_id, family, category, domain, memory_text,
                    condition, evidence_text, source_thread_id, status,
                    valid_from, valid_to, supersedes_memory_id, metadata
                ) VALUES (
                    %(memory_id)s, %(user_id)s, %(family)s, %(category)s,
                    %(domain)s, %(memory_text)s, %(condition)s,
                    %(evidence_text)s, %(source_thread_id)s, %(status)s,
                    %(valid_from)s, %(valid_to)s, %(supersedes_memory_id)s,
                    %(metadata)s
                )
                """,
                {
                    **record,
                    "memory_id": memory_id,
                    "metadata": Jsonb(record.get("metadata") or {}),
                },
            )
        return str(memory_id)

    async def upsert_memory_embedding(self, record: MemoryEmbeddingRecord) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                """
                UPDATE long_term_memory_embeddings
                SET is_current = false, updated_at = now()
                WHERE memory_id = %(memory_id)s
                  AND is_current = true
                  AND (
                    embedding_model <> %(embedding_model)s
                    OR embedding_dims <> %(embedding_dims)s
                    OR content_hash <> %(content_hash)s
                  )
                """,
                {
                    "memory_id": UUID(str(record.memory_id)),
                    "embedding_model": record.embedding_model,
                    "embedding_dims": record.embedding_dims,
                    "content_hash": record.content_hash,
                },
            )
            await conn.execute(
                """
                INSERT INTO long_term_memory_embeddings (
                    embedding_id, memory_id, embedding, embedding_model,
                    embedding_dims, content_hash, is_current
                ) VALUES (
                    %(embedding_id)s, %(memory_id)s, %(embedding)s::vector,
                    %(embedding_model)s, %(embedding_dims)s, %(content_hash)s, true
                )
                ON CONFLICT (memory_id, embedding_model, content_hash)
                DO UPDATE SET
                    embedding = EXCLUDED.embedding,
                    embedding_dims = EXCLUDED.embedding_dims,
                    is_current = true,
                    updated_at = now()
                """,
                {
                    "embedding_id": uuid4(),
                    "memory_id": UUID(str(record.memory_id)),
                    "embedding": vector_literal(record.embedding),
                    "embedding_model": record.embedding_model,
                    "embedding_dims": record.embedding_dims,
                    "content_hash": record.content_hash,
                },
            )

    async def find_memories_missing_current_embedding(
        self,
        *,
        embedding_model: str,
        embedding_dims: int,
        limit: int,
    ) -> list[TravelMemory]:
        async with self._pool.connection() as conn:
            rows = await (
                await conn.execute(
                    """
                    SELECT m.memory_id, m.user_id, m.memory_text, m.category, m.domain,
                           m.condition, m.evidence_text, m.source_thread_id, m.status,
                           m.valid_from, m.valid_to, m.supersedes_memory_id,
                           m.created_at, m.updated_at, m.metadata
                    FROM long_term_memories m
                    WHERE m.status = 'active'
                      AND (m.valid_from IS NULL OR m.valid_from <= now())
                      AND (m.valid_to IS NULL OR m.valid_to > now())
                      AND NOT EXISTS (
                        SELECT 1
                        FROM long_term_memory_embeddings e
                        WHERE e.memory_id = m.memory_id
                          AND e.embedding_model = %(embedding_model)s
                          AND e.embedding_dims = %(embedding_dims)s
                          AND e.is_current = true
                      )
                    ORDER BY m.updated_at ASC, m.created_at ASC
                    LIMIT %(limit)s
                    """,
                    {
                        "embedding_model": embedding_model,
                        "embedding_dims": embedding_dims,
                        "limit": limit,
                    },
                )
            ).fetchall()
        return [TravelMemory.from_record(dict(row)) for row in rows]

    async def semantic_search_active_memories(
        self,
        filters: MemorySearchFilters,
        *,
        query_embedding: Sequence[float],
        embedding_model: str,
        embedding_dims: int,
        distance_threshold: float,
    ) -> list[TravelMemory]:
        families = [str(family) for family in filters.families]
        params: dict[str, Any] = {
            "user_id": filters.user_id,
            "families": families,
            "limit": filters.limit,
            "query_embedding": vector_literal(query_embedding),
            "embedding_model": embedding_model,
            "embedding_dims": embedding_dims,
            "distance_threshold": distance_threshold,
        }
        domain_clause = _domain_filter_clause(filters, params).replace(
            " AND domain = ANY(%(domains)s)",
            " AND m.domain = ANY(%(domains)s)",
        )
        async with self._pool.connection() as conn:
            rows = await (
                await conn.execute(
                    f"""
                    SELECT m.memory_id, m.user_id, m.memory_text, m.category, m.domain,
                           m.condition, m.evidence_text, m.source_thread_id, m.status,
                           m.valid_from, m.valid_to, m.supersedes_memory_id,
                           m.created_at, m.updated_at, m.metadata,
                           e.embedding <=> %(query_embedding)s::vector AS distance
                    FROM long_term_memories m
                    JOIN long_term_memory_embeddings e ON e.memory_id = m.memory_id
                    WHERE m.user_id = %(user_id)s
                      AND m.family = ANY(%(families)s)
                      AND m.status = 'active'
                      AND (m.valid_from IS NULL OR m.valid_from <= now())
                      AND (m.valid_to IS NULL OR m.valid_to > now())
                      {domain_clause}
                      AND e.is_current = true
                      AND e.embedding_model = %(embedding_model)s
                      AND e.embedding_dims = %(embedding_dims)s
                      AND (e.embedding <=> %(query_embedding)s::vector) <= %(distance_threshold)s
                    ORDER BY distance ASC, m.updated_at DESC
                    LIMIT %(limit)s
                    """,
                    params,
                )
            ).fetchall()
        return [TravelMemory.from_record(dict(row)) for row in rows]

    async def fetch_transition_comparison_pool(
        self,
        *,
        user_id: str,
        category: str,
        domain: str,
        candidate_embedding: Sequence[float] | None = None,
        embedding_model: str = "",
        embedding_dims: int = 0,
    ) -> list[RankedMemory]:
        params: dict[str, Any] = {
            "user_id": user_id,
            "category": category,
            "domain": domain,
            "embedding_model": embedding_model,
            "embedding_dims": embedding_dims,
        }
        if candidate_embedding is not None and embedding_model and embedding_dims > 0:
            params["candidate_embedding"] = vector_literal(candidate_embedding)
            distance_expr = "e.embedding <=> %(candidate_embedding)s::vector"
            join_clause = """
                LEFT JOIN long_term_memory_embeddings AS e
                  ON e.memory_id = p.memory_id
                 AND e.is_current = TRUE
                 AND e.embedding_model = %(embedding_model)s
                 AND e.embedding_dims = %(embedding_dims)s
            """
        else:
            distance_expr = "NULL::double precision"
            join_clause = ""

        async with self._pool.connection() as conn:
            rows = await (
                await conn.execute(
                    f"""
                    WITH comparison_pool AS (
                        SELECT
                            m.memory_id, m.user_id, m.memory_text, m.category, m.domain,
                            m.condition, m.evidence_text, m.source_thread_id, m.status,
                            m.valid_from, m.valid_to, m.supersedes_memory_id,
                            m.created_at, m.updated_at, m.metadata
                        FROM long_term_memories AS m
                        WHERE m.user_id = %(user_id)s
                          AND m.status = 'active'
                          AND m.category = %(category)s
                          AND m.domain = %(domain)s
                          AND (m.valid_from IS NULL OR m.valid_from <= now())
                          AND (m.valid_to IS NULL OR m.valid_to > now())
                    ),
                    ranked_pool AS (
                        SELECT
                            p.*,
                            {distance_expr} AS distance
                        FROM comparison_pool AS p
                        {join_clause}
                    )
                    SELECT *
                    FROM ranked_pool
                    ORDER BY
                        (distance IS NULL) ASC,
                        distance ASC,
                        created_at DESC
                    """,
                    params,
                )
            ).fetchall()
        ranked: list[RankedMemory] = []
        for row in rows:
            payload = dict(row)
            distance = payload.pop("distance", None)
            ranked.append(
                RankedMemory(
                    memory=TravelMemory.from_record(payload),
                    distance=float(distance) if distance is not None else None,
                )
            )
        return ranked

    async def mark_memory_superseded(self, memory_id: str) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                """
                UPDATE long_term_memories
                SET status = 'superseded', updated_at = now()
                WHERE memory_id = %(memory_id)s
                """,
                {"memory_id": UUID(str(memory_id))},
            )

    async def commit_supersede(
        self, *, existing_memory_id: str, new_memory: TravelMemory
    ) -> str:
        memory_id = uuid4()
        record = apply_default_validity_if_missing(new_memory).to_record()
        if not record.get("supersedes_memory_id"):
            record["supersedes_memory_id"] = existing_memory_id
        async with self._pool.connection() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    UPDATE long_term_memories
                    SET status = 'superseded', updated_at = now()
                    WHERE memory_id = %(memory_id)s
                    """,
                    {"memory_id": UUID(str(existing_memory_id))},
                )
                await conn.execute(
                    """
                    INSERT INTO long_term_memories (
                        memory_id, user_id, family, category, domain, memory_text,
                        condition, evidence_text, source_thread_id, status,
                        valid_from, valid_to, supersedes_memory_id, metadata
                    ) VALUES (
                        %(memory_id)s, %(user_id)s, %(family)s, %(category)s,
                        %(domain)s, %(memory_text)s, %(condition)s,
                        %(evidence_text)s, %(source_thread_id)s, %(status)s,
                        %(valid_from)s, %(valid_to)s, %(supersedes_memory_id)s,
                        %(metadata)s
                    )
                    """,
                    {
                        **record,
                        "memory_id": memory_id,
                        "metadata": Jsonb(record.get("metadata") or {}),
                    },
                )
        return str(memory_id)

    async def write_audit_record(
        self,
        *,
        job_id: str | None,
        user_id: str,
        thread_id: str | None,
        decision: str,
        proposed_transition: dict[str, Any],
        rule_result: dict[str, Any] | None = None,
        verifier_result: dict[str, Any] | None = None,
        affected_memory_ids: Sequence[str] | None = None,
    ) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                """
                INSERT INTO memory_audit_records (
                    audit_id, job_id, user_id, thread_id, decision,
                    proposed_transition, rule_result, verifier_result,
                    affected_memory_ids
                ) VALUES (
                    %(audit_id)s, %(job_id)s, %(user_id)s, %(thread_id)s,
                    %(decision)s, %(proposed_transition)s, %(rule_result)s,
                    %(verifier_result)s, %(affected_memory_ids)s
                )
                """,
                {
                    "audit_id": uuid4(),
                    "job_id": UUID(str(job_id)) if job_id else None,
                    "user_id": user_id,
                    "thread_id": thread_id,
                    "decision": decision,
                    "proposed_transition": Jsonb(proposed_transition or {}),
                    "rule_result": Jsonb(rule_result or {}),
                    "verifier_result": Jsonb(verifier_result or {}),
                    "affected_memory_ids": Jsonb(list(affected_memory_ids or [])),
                },
            )

    async def enqueue_memory_job(
        self,
        *,
        user_id: str,
        thread_id: str,
        idempotency_key: str,
        final_message_id: str | None,
        checkpoint_id: str | None,
        messages: Sequence[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> MemoryJobRef:
        job_id = uuid4()
        payload = {
            "job_id": job_id,
            "user_id": str(user_id),
            "thread_id": str(thread_id),
            "idempotency_key": str(idempotency_key),
            "final_message_id": final_message_id,
            "checkpoint_id": checkpoint_id,
            "messages": Jsonb(list(messages)),
            "metadata": Jsonb(metadata or {}),
        }
        async with self._pool.connection() as conn:
            try:
                row = await (
                    await conn.execute(
                        """
                        INSERT INTO memory_jobs (
                            job_id, user_id, thread_id, idempotency_key,
                            final_message_id, checkpoint_id, messages, metadata
                        ) VALUES (
                            %(job_id)s, %(user_id)s, %(thread_id)s,
                            %(idempotency_key)s, %(final_message_id)s,
                            %(checkpoint_id)s, %(messages)s, %(metadata)s
                        )
                        RETURNING job_id, idempotency_key, status
                        """,
                        payload,
                    )
                ).fetchone()
                return MemoryJobRef(
                    job_id=str(row["job_id"]),
                    idempotency_key=str(row["idempotency_key"]),
                    status=str(row["status"]),
                    created=True,
                )
            except UniqueViolation:
                row = await (
                    await conn.execute(
                        """
                        SELECT job_id, idempotency_key, status
                        FROM memory_jobs
                        WHERE idempotency_key = %(idempotency_key)s
                        """,
                        {"idempotency_key": str(idempotency_key)},
                    )
                ).fetchone()
                return MemoryJobRef(
                    job_id=str(row["job_id"]),
                    idempotency_key=str(row["idempotency_key"]),
                    status=str(row["status"]),
                    created=False,
                )


class NoopLongTermMemoryRepository:
    async def search_active_memories(
        self, filters: MemorySearchFilters
    ) -> list[TravelMemory]:
        return []

    async def fetch_active_domain_memories(
        self,
        *,
        user_id: str,
        domain: str,
        limit: int,
    ) -> list[TravelMemory]:
        return []

    async def insert_memory(self, memory: TravelMemory) -> str:
        return memory.memory_id or "noop-memory"

    async def upsert_memory_embedding(self, record: MemoryEmbeddingRecord) -> None:
        return None

    async def find_memories_missing_current_embedding(
        self,
        *,
        embedding_model: str,
        embedding_dims: int,
        limit: int,
    ) -> list[TravelMemory]:
        return []

    async def semantic_search_active_memories(
        self,
        filters: MemorySearchFilters,
        *,
        query_embedding: Sequence[float],
        embedding_model: str,
        embedding_dims: int,
        distance_threshold: float,
    ) -> list[TravelMemory]:
        return []

    async def fetch_transition_comparison_pool(
        self,
        *,
        user_id: str,
        category: str,
        domain: str,
        candidate_embedding: Sequence[float] | None = None,
        embedding_model: str = "",
        embedding_dims: int = 0,
    ) -> list[RankedMemory]:
        return []

    async def mark_memory_superseded(self, memory_id: str) -> None:
        return None

    async def commit_supersede(
        self, *, existing_memory_id: str, new_memory: TravelMemory
    ) -> str:
        return new_memory.memory_id or "noop-memory"

    async def write_audit_record(
        self,
        *,
        job_id: str | None,
        user_id: str,
        thread_id: str | None,
        decision: str,
        proposed_transition: dict[str, Any],
        rule_result: dict[str, Any] | None = None,
        verifier_result: dict[str, Any] | None = None,
        affected_memory_ids: Sequence[str] | None = None,
    ) -> None:
        return None

    async def enqueue_memory_job(
        self,
        *,
        user_id: str,
        thread_id: str,
        idempotency_key: str,
        final_message_id: str | None,
        checkpoint_id: str | None,
        messages: Sequence[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> MemoryJobRef:
        return MemoryJobRef(
            job_id="noop",
            idempotency_key=idempotency_key,
            status="disabled",
            created=False,
        )
