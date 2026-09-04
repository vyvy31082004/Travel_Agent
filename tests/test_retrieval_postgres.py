from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memory_eval.retrieval_postgres import (
    RECALL_RANKED_SEARCH_SQL,
    MemoryClassification,
    classify_fixture_memory,
    seeded_memory_uuid,
)
from settings import Settings


def make_settings(**overrides):
    values = dict(
        database_url="postgresql://user:pass@localhost/db",
        cookie_secret="secret",
        long_term_memory_recall_enabled=False,
        long_term_memory_write_enabled=False,
    )
    values.update(overrides)
    return Settings(**values)


def test_recall_ranked_search_sql_has_production_filters_without_threshold():
    assert "m.user_id = %(user_id)s" in RECALL_RANKED_SEARCH_SQL
    assert "m.family = ANY(%(families)s)" in RECALL_RANKED_SEARCH_SQL
    assert "m.status = 'active'" in RECALL_RANKED_SEARCH_SQL
    assert "e.is_current = true" in RECALL_RANKED_SEARCH_SQL
    assert "distance_threshold" not in RECALL_RANKED_SEARCH_SQL
    assert "<=>" in RECALL_RANKED_SEARCH_SQL


def test_seeded_uuid_is_deterministic():
    first = seeded_memory_uuid("exact_001", "rel-exact_001")
    second = seeded_memory_uuid("exact_001", "rel-exact_001")
    third = seeded_memory_uuid("exact_002", "rel-exact_001")
    assert first == second
    assert first != third
    assert isinstance(first, uuid.UUID)


def test_classify_gold_forbidden_and_irrelevant():
    case_user = "user-1"
    gold = classify_fixture_memory(
        {
            "memory_id": "rel-1",
            "user_id": case_user,
            "memory_text": "thích khách sạn boutique",
            "category": "hotel_preference",
            "domain": "hotel",
            "evidence_text": "Tôi thích khách sạn boutique",
            "source_thread_id": "t1",
            "status": "active",
            "relevant": True,
        },
        case_user_id=case_user,
    )
    assert gold.classification == MemoryClassification.GOLD

    forbidden_user = classify_fixture_memory(
        {
            "memory_id": "xuser-u2",
            "user_id": "user-2",
            "memory_text": "thích khách sạn boutique",
            "category": "hotel_preference",
            "domain": "hotel",
            "evidence_text": "Tôi thích khách sạn boutique",
            "source_thread_id": "t1",
            "status": "active",
            "relevant": False,
        },
        case_user_id=case_user,
    )
    assert forbidden_user.classification == MemoryClassification.FORBIDDEN
    assert forbidden_user.forbidden_reason == "cross_user"

    forbidden_inactive = classify_fixture_memory(
        {
            "memory_id": "lifecycle-old",
            "user_id": case_user,
            "memory_text": "thích khách sạn gần biển",
            "category": "hotel_preference",
            "domain": "hotel",
            "evidence_text": "Tôi thích khách sạn gần biển",
            "source_thread_id": "t1",
            "status": "superseded",
            "relevant": False,
        },
        case_user_id=case_user,
    )
    assert forbidden_inactive.classification == MemoryClassification.FORBIDDEN
    assert forbidden_inactive.forbidden_reason == "inactive_status"

    expired = classify_fixture_memory(
        {
            "memory_id": "temporal-expired",
            "user_id": case_user,
            "memory_text": "không ăn hải sản",
            "category": "general_preference",
            "domain": "general",
            "evidence_text": "Tôi không ăn hải sản",
            "source_thread_id": "t1",
            "status": "active",
            "relevant": False,
            "valid_to": "2020-01-01T00:00:00+00:00",
        },
        case_user_id=case_user,
    )
    assert expired.classification == MemoryClassification.FORBIDDEN
    assert expired.forbidden_reason == "inactive_window"

    irrelevant = classify_fixture_memory(
        {
            "memory_id": "noise-1",
            "user_id": case_user,
            "memory_text": "ưu tiên bay thẳng",
            "category": "flight_preference",
            "domain": "flight",
            "evidence_text": "Tôi ưu tiên bay thẳng",
            "source_thread_id": "t1",
            "status": "active",
            "relevant": False,
        },
        case_user_id=case_user,
    )
    assert irrelevant.classification == MemoryClassification.IRRELEVANT


@pytest.mark.skipif(
    not __import__("os").getenv("RUN_POSTGRES_INTEGRATION"),
    reason="RUN_POSTGRES_INTEGRATION required",
)
def test_collect_case_records_integration():
    import asyncio
    import selectors
    import sys

    from memory.embeddings import MemoryEmbeddingService
    from infrastructure.postgres import create_pool
    from memory_eval.retrieval_postgres import collect_case_records
    from repositories.long_term_memory import PostgresLongTermMemoryRepository
    from settings import get_settings

    class FakeEmbeddingProvider:
        def __init__(self, dims: int):
            self._dims = dims
            self._rel = [1.0] + [0.0] * (dims - 1)
            self._noise = [0.0, 1.0] + [0.0] * (dims - 2)

        async def embed_query(self, text):
            return self._rel

        async def embed_documents(self, texts):
            return [
                self._rel if "boutique" in text else self._noise
                for text in texts
            ]

    settings = get_settings()

    async def _run():
        pool = create_pool(settings)
        await pool.open(wait=True)
        provider = FakeEmbeddingProvider(settings.long_term_memory_vector_dims)
        embedding_service = MemoryEmbeddingService(
            settings=settings,
            provider=provider,
        )
        repository = PostgresLongTermMemoryRepository(pool)
        case = {
            "case_id": "itest_collect_001",
            "user_id": "user-1",
            "query": "hotel boutique",
            "memories": [
                {
                    "memory_id": "itest-rel",
                    "user_id": "user-1",
                    "memory_text": "thích khách sạn boutique",
                    "category": "hotel_preference",
                    "domain": "hotel",
                    "evidence_text": "Tôi thích khách sạn boutique",
                    "source_thread_id": "t1",
                    "status": "active",
                    "relevant": True,
                },
                {
                    "memory_id": "itest-noise",
                    "user_id": "user-1",
                    "memory_text": "ưu tiên bay thẳng",
                    "category": "flight_preference",
                    "domain": "flight",
                    "evidence_text": "Tôi ưu tiên bay thẳng",
                    "source_thread_id": "t1",
                    "status": "active",
                    "relevant": False,
                },
            ],
        }
        try:
            return await collect_case_records(
                case,
                pool=pool,
                repository=repository,
                embedding_service=embedding_service,
                top_k=5,
            )
        finally:
            await pool.close()

    if sys.platform == "win32":
        records = asyncio.run(
            _run(),
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )
    else:
        records = asyncio.run(_run())

    summary = next(row for row in records if row["record_type"] == "case_summary")
    scores = [row for row in records if row["record_type"] == "score"]
    assert summary["gold_relevant_count"] == 1
    assert summary["gold_relevant_memory_ids"] == ["itest-rel"]
    assert scores
    assert scores[0]["fixture_memory_id"] == "itest-rel"
    assert "cosine_distance" in scores[0]
