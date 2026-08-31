from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Sequence

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from memory.embeddings import (
    MemoryEmbeddingService,
    memory_content_hash,
    vector_literal,
)
from memory.long_term import (
    MemoryFamily,
    MemoryStatus,
    TravelMemory,
    format_memory_for_prompt,
)
from memory_eval.common import load_jsonl, memory_from_dict
from memory_eval.suites import filter_rows_by_split
from repositories.long_term_memory import (
    MemoryEmbeddingRecord,
    PostgresLongTermMemoryRepository,
)
from settings import Settings

EVAL_BRANCH = "pgvector_semantic_only"
EVAL_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

# Copied from PostgresLongTermMemoryRepository.semantic_search_active_memories (L300-318)
# without distance_threshold — keep in sync with production recall filters.
RECALL_RANKED_SEARCH_SQL = """
    SELECT m.memory_id, m.memory_text,
           e.embedding <=> %(query_embedding)s::vector AS distance
    FROM long_term_memories m
    JOIN long_term_memory_embeddings e ON e.memory_id = m.memory_id
    WHERE m.user_id = %(user_id)s
      AND m.family = ANY(%(families)s)
      AND m.status = 'active'
      AND (m.valid_from IS NULL OR m.valid_from <= now())
      AND (m.valid_to IS NULL OR m.valid_to > now())
      AND e.is_current = true
      AND e.embedding_model = %(embedding_model)s
      AND e.embedding_dims = %(embedding_dims)s
    ORDER BY distance ASC, m.updated_at DESC
    LIMIT %(limit)s
"""

INSERT_EVAL_MEMORY_SQL = """
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
"""

DELETE_EVAL_EMBEDDINGS_SQL = """
    DELETE FROM long_term_memory_embeddings
    WHERE memory_id IN (
        SELECT memory_id FROM long_term_memories
        WHERE user_id LIKE %(user_prefix)s
    )
"""

DELETE_EVAL_MEMORIES_SQL = """
    DELETE FROM long_term_memories
    WHERE user_id LIKE %(user_prefix)s
"""


class MemoryClassification(StrEnum):
    GOLD = "gold"
    FORBIDDEN = "forbidden"
    IRRELEVANT = "irrelevant"


@dataclass(frozen=True)
class ClassifiedMemory:
    fixture_memory_id: str
    memory: TravelMemory
    classification: MemoryClassification
    forbidden_reason: str | None = None


def eval_user_id(case_id: str, original_user_id: str) -> str:
    return f"eval-{case_id}:{original_user_id}"


def eval_user_prefix(case_id: str) -> str:
    return f"eval-{case_id}:%"


def seeded_memory_uuid(case_id: str, fixture_memory_id: str) -> uuid.UUID:
    return uuid.uuid5(
        EVAL_NAMESPACE, f"retrieval-eval:{case_id}:{fixture_memory_id}"
    )


def is_recall_eligible(memory: TravelMemory, case_user_id: str) -> bool:
    if memory.user_id != case_user_id:
        return False
    if MemoryStatus(memory.status) != MemoryStatus.ACTIVE:
        return False
    return memory.is_active


def classify_fixture_memory(
    raw: dict[str, Any], *, case_user_id: str
) -> ClassifiedMemory:
    memory = memory_from_dict(raw)
    fixture_id = str(raw["memory_id"])
    relevant = bool(raw.get("relevant"))

    if memory.user_id != case_user_id:
        return ClassifiedMemory(
            fixture_memory_id=fixture_id,
            memory=memory,
            classification=MemoryClassification.FORBIDDEN,
            forbidden_reason="cross_user",
        )
    if MemoryStatus(memory.status) != MemoryStatus.ACTIVE:
        return ClassifiedMemory(
            fixture_memory_id=fixture_id,
            memory=memory,
            classification=MemoryClassification.FORBIDDEN,
            forbidden_reason="inactive_status",
        )
    if not memory.is_active:
        return ClassifiedMemory(
            fixture_memory_id=fixture_id,
            memory=memory,
            classification=MemoryClassification.FORBIDDEN,
            forbidden_reason="inactive_window",
        )
    if relevant:
        return ClassifiedMemory(
            fixture_memory_id=fixture_id,
            memory=memory,
            classification=MemoryClassification.GOLD,
        )
    return ClassifiedMemory(
        fixture_memory_id=fixture_id,
        memory=memory,
        classification=MemoryClassification.IRRELEVANT,
    )


def classify_case_memories(case: dict[str, Any]) -> list[ClassifiedMemory]:
    case_user_id = str(case["user_id"])
    return [
        classify_fixture_memory(raw, case_user_id=case_user_id)
        for raw in case.get("memories") or []
    ]


def case_families(
    classified: Sequence[ClassifiedMemory], *, case_user_id: str
) -> tuple[MemoryFamily, ...]:
    families = {
        MemoryFamily(item.memory.family)
        for item in classified
        if str(item.memory.user_id or "") == case_user_id
    }
    return tuple(families or {MemoryFamily.TRAVEL_PREFERENCES})


async def insert_eval_memory(
    pool: AsyncConnectionPool,
    *,
    memory: TravelMemory,
    seeded_uuid_value: uuid.UUID,
    user_id: str,
) -> None:
    record = memory.to_record()
    async with pool.connection() as conn:
        await conn.execute(
            INSERT_EVAL_MEMORY_SQL,
            {
                **record,
                "memory_id": seeded_uuid_value,
                "user_id": user_id,
                "metadata": Jsonb(record.get("metadata") or {}),
            },
        )


async def delete_eval_case(pool: AsyncConnectionPool, case_id: str) -> None:
    params = {"user_prefix": eval_user_prefix(case_id)}
    async with pool.connection() as conn:
        await conn.execute(DELETE_EVAL_EMBEDDINGS_SQL, params)
        await conn.execute(DELETE_EVAL_MEMORIES_SQL, params)


async def search_ranked_distances(
    pool: AsyncConnectionPool,
    *,
    user_id: str,
    families: Sequence[MemoryFamily],
    query_embedding: Sequence[float],
    embedding_model: str,
    embedding_dims: int,
    limit: int,
) -> list[tuple[uuid.UUID, float]]:
    async with pool.connection() as conn:
        rows = await (
            await conn.execute(
                RECALL_RANKED_SEARCH_SQL,
                {
                    "user_id": user_id,
                    "families": [str(family) for family in families],
                    "limit": limit,
                    "query_embedding": vector_literal(query_embedding),
                    "embedding_model": embedding_model,
                    "embedding_dims": embedding_dims,
                },
            )
        ).fetchall()
    results: list[tuple[uuid.UUID, float]] = []
    for row in rows:
        results.append((row["memory_id"], float(row["distance"])))
    return results


async def collect_case_records(
    case: dict[str, Any],
    *,
    pool: AsyncConnectionPool,
    repository: PostgresLongTermMemoryRepository,
    embedding_service: MemoryEmbeddingService,
    top_k: int,
) -> list[dict[str, Any]]:
    case_id = str(case["case_id"])
    case_user_id = str(case["user_id"])
    await delete_eval_case(pool, case_id)
    classified = classify_case_memories(case)
    case_user = eval_user_id(case_id, case_user_id)
    families = case_families(classified, case_user_id=case_user_id)

    uuid_to_fixture: dict[str, str] = {}
    fixture_to_gold: dict[str, bool] = {}
    fixture_to_prompt: dict[str, str] = {}

    for item in classified:
        seeded = seeded_memory_uuid(case_id, item.fixture_memory_id)
        uuid_to_fixture[str(seeded)] = item.fixture_memory_id
        fixture_to_gold[item.fixture_memory_id] = (
            item.classification == MemoryClassification.GOLD
        )
        prompt_memory = replace(item.memory, memory_id=str(seeded))
        fixture_to_prompt[item.fixture_memory_id] = format_memory_for_prompt(
            prompt_memory
        )
        eval_user = eval_user_id(case_id, str(item.memory.user_id or case["user_id"]))
        await insert_eval_memory(
            pool,
            memory=item.memory,
            seeded_uuid_value=seeded,
            user_id=eval_user,
        )
        if MemoryStatus(item.memory.status) == MemoryStatus.ACTIVE and item.memory.is_active:
            vector = await embedding_service.embed_memory(item.memory)
            await repository.upsert_memory_embedding(
                MemoryEmbeddingRecord(
                    memory_id=str(seeded),
                    embedding=vector,
                    embedding_model=embedding_service.model,
                    embedding_dims=embedding_service.dims,
                    content_hash=memory_content_hash(
                        item.memory, model=embedding_service.model
                    ),
                )
            )

    query_embedding = await embedding_service.embed_query(str(case["query"]))
    ranked = await search_ranked_distances(
        pool,
        user_id=case_user,
        families=families,
        query_embedding=query_embedding,
        embedding_model=embedding_service.model,
        embedding_dims=embedding_service.dims,
        limit=top_k,
    )

    gold_ids = [
        item.fixture_memory_id
        for item in classified
        if item.classification == MemoryClassification.GOLD
    ]
    forbidden_ids = [
        item.fixture_memory_id
        for item in classified
        if item.classification == MemoryClassification.FORBIDDEN
    ]
    forbidden_reasons = {
        item.fixture_memory_id: item.forbidden_reason
        for item in classified
        if item.classification == MemoryClassification.FORBIDDEN
        and item.forbidden_reason
    }

    records: list[dict[str, Any]] = [
        {
            "record_type": "case_summary",
            "case_id": case_id,
            "query": case["query"],
            "eval_branch": EVAL_BRANCH,
            "gold_relevant_memory_ids": gold_ids,
            "gold_relevant_count": len(gold_ids),
            "forbidden_memory_ids": forbidden_ids,
            "forbidden_reasons": forbidden_reasons,
            "retrieval_candidate_limit": top_k,
            "expect_empty_recall": bool(case.get("expect_empty_recall")),
        }
    ]

    returned_fixture_ids: set[str] = set()
    for rank, (seeded_uuid_key, distance) in enumerate(ranked, start=1):
        fixture_id = uuid_to_fixture[str(seeded_uuid_key)]
        returned_fixture_ids.add(fixture_id)
        records.append(
            {
                "record_type": "score",
                "case_id": case_id,
                "fixture_memory_id": fixture_id,
                "seeded_memory_uuid": str(seeded_uuid_key),
                "rank": rank,
                "cosine_distance": distance,
                "gold_relevant": fixture_to_gold.get(fixture_id, False),
                "context_prompt_text": fixture_to_prompt.get(fixture_id, ""),
            }
        )

    for fixture_id in gold_ids:
        if fixture_id not in returned_fixture_ids:
            records.append(
                {
                    "record_type": "not_returned",
                    "case_id": case_id,
                    "fixture_memory_id": fixture_id,
                    "gold_relevant": True,
                }
            )

    await delete_eval_case(pool, case_id)
    return records


async def collect_retrieval_distance_scores(
    path: str | Path,
    *,
    settings: Settings,
    pool: AsyncConnectionPool,
    split: str = "development",
    top_k: int = 20,
    embedding_service: MemoryEmbeddingService | None = None,
) -> list[dict[str, Any]]:
    rows = filter_rows_by_split(load_jsonl(path), split)
    repository = PostgresLongTermMemoryRepository(pool)
    service = embedding_service or MemoryEmbeddingService(settings=settings)

    all_records: list[dict[str, Any]] = [
        {
            "record_type": "run_metadata",
            "eval_branch": EVAL_BRANCH,
            "split": split,
            "case_count": len(rows),
            "retrieval_candidate_limit": top_k,
            "embedding_model": service.model,
            "embedding_dims": service.dims,
            "collected_at": datetime.now(timezone.utc).isoformat(),
        }
    ]

    for case in rows:
        all_records.extend(
            await collect_case_records(
                case,
                pool=pool,
                repository=repository,
                embedding_service=service,
                top_k=top_k,
            )
        )
    return all_records


def write_distance_scores_jsonl(
    path: str | Path, records: Sequence[dict[str, Any]]
) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_distance_scores_jsonl(path: str | Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at line {line_number}: {exc}") from exc
            if not isinstance(raw, dict):
                raise ValueError(f"invalid JSONL at line {line_number}: expected object")
            records.append(raw)
    return records
