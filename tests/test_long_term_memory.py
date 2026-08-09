import asyncio
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from memory.commit import MemoryCommitAdapter
from memory.embeddings import (
    EmbeddingError,
    MemoryEmbeddingService,
    memory_content_hash,
    validate_embedding_dimensions,
)
from memory.consolidation import (
    LangMemCandidateExtractor,
    LangMemTravelMemory,
    MemoryTransition,
    TransitionAction,
    build_candidate_extractor,
    calculate_transition,
    extract_candidate_memories,
    normalize_langmem_outputs,
    validate_memory_candidate,
)
from memory.long_term import (
    MemoryCategory,
    MemoryDomain,
    MemoryFamily,
    MemoryStatus,
    TravelMemory,
    format_memory_for_prompt,
    memory_namespace,
    namespace_for_category,
)
from repositories.long_term_memory import (
    MemoryEmbeddingRecord,
    MemorySearchFilters,
    NoopLongTermMemoryRepository,
)
from memory.verifier import DeterministicMemoryVerifier
from services.long_term_memory import MemoryService, memory_job_idempotency_key
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


def test_vector_settings_validate_distance_threshold():
    assert make_settings(long_term_memory_vector_distance_threshold=0.5)
    with pytest.raises(ValueError):
        make_settings(long_term_memory_vector_distance_threshold=2.5)


def test_travel_memory_validation_namespace_and_lifecycle():
    memory = TravelMemory(
        memory_id="mem-1",
        user_id="user-1",
        memory_text="thích khách sạn boutique gần biển",
        category=MemoryCategory.HOTEL_PREFERENCE,
        domain=MemoryDomain.HOTEL,
        evidence_text="Tôi thích khách sạn boutique gần biển",
        source_thread_id="thread-1",
    )
    assert memory.family == MemoryFamily.TRAVEL_PREFERENCES
    assert memory.is_active
    assert memory_namespace("user-1", MemoryFamily.TRAVEL_PREFERENCES) == (
        "users",
        "user-1",
        "travel_preferences",
    )
    assert namespace_for_category("user-1", MemoryCategory.PROFILE_FACT) == (
        "users",
        "user-1",
        "profile_facts",
    )
    assert "boutique" in format_memory_for_prompt(memory)

    expired = replace(memory, valid_to=datetime.now(timezone.utc) - timedelta(days=1))
    assert not expired.is_active
    superseded = replace(memory, status=MemoryStatus.SUPERSEDED)
    assert not superseded.is_active


def test_recall_disabled_and_no_user_fallback():
    service = MemoryService(settings=make_settings(long_term_memory_recall_enabled=False))
    result = asyncio.run(service.recall(user_id="user-1", query="khách sạn"))
    assert result.memory_context == ""
    assert result.recalled_memory_ids == []

    enabled = MemoryService(settings=make_settings(long_term_memory_recall_enabled=True))
    result = asyncio.run(enabled.recall(user_id=None, query="khách sạn"))
    assert result.memory_context == ""


class FakeRepo(NoopLongTermMemoryRepository):
    def __init__(self, memories, *, vector_memories=None, vector_error=None):
        self.memories = memories
        self.vector_memories = vector_memories
        self.vector_error = vector_error
        self.filters = None
        self.vector_filters = None
        self.vector_kwargs = None

    async def search_active_memories(self, filters: MemorySearchFilters):
        self.filters = filters
        return self.memories

    async def semantic_search_active_memories(self, filters: MemorySearchFilters, **kwargs):
        self.vector_filters = filters
        self.vector_kwargs = kwargs
        if self.vector_error:
            raise self.vector_error
        return self.vector_memories if self.vector_memories is not None else self.memories


def test_recall_filters_active_memories_and_limit():
    active = TravelMemory(
        memory_id="active-1",
        user_id="user-1",
        memory_text="ưu tiên bay thẳng",
        category=MemoryCategory.FLIGHT_PREFERENCE,
        domain=MemoryDomain.FLIGHT,
        evidence_text="Tôi ưu tiên bay thẳng",
        source_thread_id="thread-1",
    )
    superseded = replace(active, memory_id="old-1", status=MemoryStatus.SUPERSEDED)
    repo = FakeRepo([active, superseded])
    service = MemoryService(
        settings=make_settings(
            long_term_memory_recall_enabled=True,
            long_term_memory_recall_limit=1,
        ),
        repository=repo,
    )
    result = asyncio.run(service.recall(user_id="user-1", query="bay"))
    assert result.recalled_memory_ids == ["active-1"]
    assert repo.filters.user_id == "user-1"
    assert repo.filters.limit == 1
    assert repo.filters.families == (MemoryFamily.TRAVEL_PREFERENCES,)


def test_vector_recall_success_and_disabled_fallback_paths():
    active = TravelMemory(
        memory_id="vector-1",
        user_id="user-1",
        memory_text="thích khách sạn boutique gần biển",
        category=MemoryCategory.HOTEL_PREFERENCE,
        domain=MemoryDomain.HOTEL,
        evidence_text="Tôi thích khách sạn boutique gần biển",
        source_thread_id="thread-1",
    )
    repo = FakeRepo([], vector_memories=[active])
    embedding_service = MemoryEmbeddingService(
        settings=make_settings(long_term_memory_vector_dims=3),
        provider=FakeEmbeddingProvider(query_vector=[0.1, 0.2, 0.3]),
    )
    service = MemoryService(
        settings=make_settings(
            long_term_memory_recall_enabled=True,
            long_term_memory_vector_search_enabled=True,
            long_term_memory_vector_dims=3,
            long_term_memory_vector_distance_threshold=0.42,
        ),
        repository=repo,
        embedding_service=embedding_service,
    )
    result = asyncio.run(service.recall(user_id="user-1", query="resort sát biển"))
    assert result.recalled_memory_ids == ["vector-1"]
    assert repo.vector_filters.user_id == "user-1"
    assert repo.vector_kwargs["query_embedding"] == [0.1, 0.2, 0.3]
    assert repo.vector_kwargs["embedding_dims"] == 3
    assert repo.vector_kwargs["distance_threshold"] == 0.42

    disabled_repo = FakeRepo([active])
    disabled_service = MemoryService(
        settings=make_settings(
            long_term_memory_recall_enabled=True,
            long_term_memory_vector_search_enabled=False,
        ),
        repository=disabled_repo,
        embedding_service=embedding_service,
    )
    result = asyncio.run(disabled_service.recall(user_id="user-1", query="resort"))
    assert result.recalled_memory_ids == ["vector-1"]
    assert disabled_repo.vector_filters is None


def test_vector_recall_failure_falls_back_to_deterministic():
    active = TravelMemory(
        memory_id="deterministic-1",
        user_id="user-1",
        memory_text="ưu tiên bay thẳng",
        category=MemoryCategory.FLIGHT_PREFERENCE,
        domain=MemoryDomain.FLIGHT,
        evidence_text="Tôi ưu tiên bay thẳng",
        source_thread_id="thread-1",
    )
    repo = FakeRepo([active])
    service = MemoryService(
        settings=make_settings(
            long_term_memory_recall_enabled=True,
            long_term_memory_vector_search_enabled=True,
            long_term_memory_vector_fallback_enabled=True,
            long_term_memory_vector_dims=3,
        ),
        repository=repo,
        embedding_service=MemoryEmbeddingService(
            settings=make_settings(long_term_memory_vector_dims=3),
            provider=FakeEmbeddingProvider(error=EmbeddingError("provider down")),
        ),
    )
    result = asyncio.run(service.recall(user_id="user-1", query="bay nhanh"))
    assert result.recalled_memory_ids == ["deterministic-1"]
    assert repo.filters.user_id == "user-1"


def test_write_disabled_does_not_enqueue_job():
    service = MemoryService(settings=make_settings(long_term_memory_write_enabled=False))
    result = asyncio.run(
        service.enqueue_final_turn(
            user_id="user-1",
            thread_id="thread-1",
            final_message_id="msg-1",
            checkpoint_id=None,
            messages=[{"type": "human", "content": "Tôi thích bay thẳng"}],
        )
    )
    assert result is None


def test_idempotency_key_is_stable():
    first = memory_job_idempotency_key(
        user_id="u", thread_id="t", final_message_id="m", checkpoint_id=None
    )
    second = memory_job_idempotency_key(
        user_id="u", thread_id="t", final_message_id="m", checkpoint_id=None
    )
    assert first == second
    assert len(first) == 64


class FakeEmbeddingProvider:
    def __init__(self, *, query_vector=None, document_vectors=None, error=None):
        self.query_vector = query_vector or [0.1, 0.2, 0.3]
        self.document_vectors = document_vectors or [[0.1, 0.2, 0.3]]
        self.error = error
        self.query_calls = []
        self.document_calls = []

    async def embed_query(self, text):
        self.query_calls.append(text)
        if self.error:
            raise self.error
        return self.query_vector

    async def embed_documents(self, texts):
        self.document_calls.append(list(texts))
        if self.error:
            raise self.error
        return self.document_vectors


def test_embedding_dimension_validation_and_content_hash():
    vector = validate_embedding_dimensions([1.0, 2.0, 3.0], expected_dims=3)
    assert vector == [1.0, 2.0, 3.0]
    with pytest.raises(EmbeddingError):
        validate_embedding_dimensions([1.0, 2.0], expected_dims=3)
    with pytest.raises(EmbeddingError):
        validate_embedding_dimensions([1.0, float("nan"), 3.0], expected_dims=3)

    memory = TravelMemory(
        memory_id="mem-1",
        user_id="user-1",
        memory_text="ưu tiên bay thẳng",
        category=MemoryCategory.FLIGHT_PREFERENCE,
        domain=MemoryDomain.FLIGHT,
        evidence_text="Tôi ưu tiên bay thẳng",
        source_thread_id="thread-1",
    )
    first = memory_content_hash(memory, model="models/gemini-embedding-001")
    second = memory_content_hash(memory, model="models/gemini-embedding-001")
    other_model = memory_content_hash(memory, model="other-model")
    assert first == second
    assert first != other_model


def test_memory_embedding_service_rejects_malformed_provider_output():
    service = MemoryEmbeddingService(
        settings=make_settings(long_term_memory_vector_dims=3),
        provider=FakeEmbeddingProvider(query_vector=[1.0, 2.0]),
    )
    with pytest.raises(EmbeddingError):
        asyncio.run(service.embed_query("khách sạn gần biển"))


def test_candidate_extraction_validation_and_transitions():
    candidates = extract_candidate_memories(
        [{"type": "human", "content": "Tôi thích khách sạn boutique gần biển"}],
        user_id="user-1",
        thread_id="thread-1",
    )
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.category == MemoryCategory.HOTEL_PREFERENCE
    assert validate_memory_candidate(candidate).ok
    assert calculate_transition(candidate, []).action == TransitionAction.INSERT

    duplicate = replace(candidate, memory_id="mem-1")
    assert calculate_transition(candidate, [duplicate]).action == TransitionAction.NOOP

    sensitive = TravelMemory(
        memory_text="mật khẩu của tôi là abc",
        category=MemoryCategory.PROFILE_FACT,
        domain=MemoryDomain.GENERAL,
        evidence_text="mật khẩu của tôi là abc",
        source_thread_id="thread-1",
    )
    rule = validate_memory_candidate(sensitive)
    assert not rule.ok
    assert any("sensitive" in reason for reason in rule.reasons)


class CommitRepo(NoopLongTermMemoryRepository):
    def __init__(self):
        self.inserted = []
        self.superseded = []
        self.audits = []
        self.embeddings = []

    async def insert_memory(self, memory):
        self.inserted.append(memory)
        return "inserted-1"

    async def upsert_memory_embedding(self, record: MemoryEmbeddingRecord) -> None:
        self.embeddings.append(record)

    async def mark_memory_superseded(self, memory_id):
        self.superseded.append(memory_id)

    async def write_audit_record(self, **kwargs):
        self.audits.append(kwargs)


def test_commit_adapter_approve_reject_and_audit():
    candidate = TravelMemory(
        memory_text="ưu tiên bay thẳng",
        category=MemoryCategory.FLIGHT_PREFERENCE,
        domain=MemoryDomain.FLIGHT,
        evidence_text="Tôi ưu tiên bay thẳng",
        source_thread_id="thread-1",
    )
    repo = CommitRepo()
    adapter = MemoryCommitAdapter(
        repository=repo, verifier=DeterministicMemoryVerifier()
    )
    result = asyncio.run(
        adapter.verify_and_commit(
            transition=MemoryTransition(TransitionAction.INSERT, candidate=candidate),
            user_id="user-1",
            thread_id="thread-1",
            job_id=None,
        )
    )
    assert result.decision == "approve"
    assert result.affected_memory_ids == ["inserted-1"]
    assert repo.inserted == [candidate]
    assert repo.audits[-1]["decision"] == "approve"

    embedding_repo = CommitRepo()
    embedding_adapter = MemoryCommitAdapter(
        repository=embedding_repo,
        verifier=DeterministicMemoryVerifier(),
        embedding_service=MemoryEmbeddingService(
            settings=make_settings(long_term_memory_vector_dims=3),
            provider=FakeEmbeddingProvider(document_vectors=[[0.1, 0.2, 0.3]]),
        ),
    )
    asyncio.run(
        embedding_adapter.verify_and_commit(
            transition=MemoryTransition(TransitionAction.INSERT, candidate=candidate),
            user_id="user-1",
            thread_id="thread-1",
            job_id=None,
        )
    )
    assert len(embedding_repo.embeddings) == 1
    assert embedding_repo.embeddings[0].memory_id == "inserted-1"

    reject = asyncio.run(
        adapter.verify_and_commit(
            transition=MemoryTransition(
                TransitionAction.REJECT, candidate=candidate, reasons=["bad"]
            ),
            user_id="user-1",
            thread_id="thread-1",
            job_id=None,
        )
    )
    assert reject.decision == "reject"
    assert repo.audits[-1]["decision"] == "reject"


class FakeLangMemManager:
    def __init__(self, outputs):
        self.outputs = outputs
        self.inputs = []

    async def ainvoke(self, payload):
        self.inputs.append(payload)
        return self.outputs


def test_langmem_extractor_normalizes_successful_output():
    manager = FakeLangMemManager(
        [
            type(
                "Extracted",
                (),
                {
                    "content": LangMemTravelMemory(
                        memory_text="ưu tiên bay thẳng",
                        category=MemoryCategory.FLIGHT_PREFERENCE,
                        domain=MemoryDomain.FLIGHT,
                        evidence_text="Tôi ưu tiên bay thẳng",
                    )
                },
            )()
        ]
    )
    extractor = LangMemCandidateExtractor(manager=manager)
    candidates = asyncio.run(
        extractor.extract(
            [{"type": "human", "content": "Tôi ưu tiên bay thẳng"}],
            user_id="user-1",
            thread_id="thread-1",
        )
    )
    assert len(candidates) == 1
    assert candidates[0].category == MemoryCategory.FLIGHT_PREFERENCE
    assert manager.inputs[0]["existing"] == []


def test_langmem_normalizer_rejects_malformed_unsupported_output():
    outputs = [
        {"memory_text": "ưu tiên khách sạn boutique", "unexpected": "field"},
        {
            "memory_text": "khách sạn từ tool",
            "category": "hotel_preference",
            "domain": "hotel",
            "evidence_text": "search_id=abc total_results=10",
        },
    ]
    candidates = normalize_langmem_outputs(
        outputs,
        user_id="user-1",
        thread_id="thread-1",
        fallback_evidence="Tôi thích khách sạn boutique",
    )
    assert candidates == []


def test_candidate_extractor_config_selects_deterministic():
    extractor = build_candidate_extractor(
        make_settings(long_term_memory_extractor="deterministic")
    )
    candidates = asyncio.run(
        extractor.extract(
            [{"type": "human", "content": "Tôi thích khách sạn boutique"}],
            user_id="user-1",
            thread_id="thread-1",
        )
    )
    assert len(candidates) == 1


def test_tool_only_messages_are_not_extracted():
    candidates = extract_candidate_memories(
        [{"type": "tool", "content": "search_id=abc total_results=10"}],
        user_id="user-1",
        thread_id="thread-1",
    )
    assert candidates == []
