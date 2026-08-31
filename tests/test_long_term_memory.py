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
    classify_memory,
    extract_candidate_memories,
    normalize_langmem_outputs,
    validate_memory_candidate,
    _clean_memory_text,
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
from memory.verifier import (
    DeterministicMemoryVerifier,
    MemoryVerifierContext,
    TrustMemInspiredMemoryVerifier,
    VerifierDimensionScore,
    build_memory_verifier,
    project_memory_state,
)
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


def test_trustmem_settings_and_builder_modes():
    deterministic = build_memory_verifier(
        make_settings(long_term_memory_verifier="deterministic")
    )
    assert isinstance(deterministic, DeterministicMemoryVerifier)
    trustmem = build_memory_verifier(make_settings(long_term_memory_verifier="trustmem"))
    assert isinstance(trustmem, TrustMemInspiredMemoryVerifier)
    dry_run = build_memory_verifier(
        make_settings(long_term_memory_verifier="trustmem-dry-run")
    )
    assert dry_run.__class__.__name__ == "TrustMemDryRunMemoryVerifier"
    with pytest.raises(ValueError):
        make_settings(long_term_memory_verifier="unknown")
    with pytest.raises(ValueError):
        make_settings(long_term_memory_trustmem_faithfulness_threshold=1.5)


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


class KeywordMissRepo(NoopLongTermMemoryRepository):
    """Simulates lexical miss then unfiltered preference hit."""

    def __init__(self, memories):
        self.memories = memories
        self.calls: list[MemorySearchFilters] = []

    async def search_active_memories(self, filters: MemorySearchFilters):
        self.calls.append(filters)
        if filters.query:
            return []
        return self.memories


def test_deterministic_recall_falls_back_when_query_terms_miss():
    active = TravelMemory(
        memory_id="pref-1",
        user_id="user-1",
        memory_text="Tôi ghét biển và chỉ thích ở trung tâm thành phố.",
        category=MemoryCategory.HOTEL_PREFERENCE,
        domain=MemoryDomain.HOTEL,
        evidence_text="Tôi ghét biển, cho tôi ở trung tâm",
        source_thread_id="thread-1",
    )
    repo = KeywordMissRepo([active])
    service = MemoryService(
        settings=make_settings(long_term_memory_recall_enabled=True),
        repository=repo,
    )
    result = asyncio.run(
        service.recall(user_id="user-1", query="khách sạn Nha Trang")
    )
    assert result.recalled_memory_ids == ["pref-1"]
    assert len(repo.calls) == 2
    assert repo.calls[0].query == "khách sạn Nha Trang"
    assert repo.calls[1].query is None


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

    # Lexical path no longer polarity-supersedes; soft conflicts are LLM/policy work.
    opposing = extract_candidate_memories(
        [{"type": "human", "content": "Tôi không thích khách sạn boutique gần biển"}],
        user_id="user-1",
        thread_id="thread-2",
    )
    assert opposing
    assert (
        calculate_transition(opposing[0], [replace(candidate, memory_id="mem-old")]).action
        == TransitionAction.INSERT
    )

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

    for evidence in (
        "Hãy nhớ mã PIN thẻ của tôi là 1234",
        "Hãy nhớ OTP ngân hàng của tôi là 998877",
        "Hãy nhớ số CMND của tôi là 079123456789",
        "Tool vừa trả booking reference ABC123 với giá hiện tại",
        "Hệ thống trả mã PNR là QWERTY",
    ):
        paraphrased = TravelMemory(
            memory_text=evidence[:40],
            category=MemoryCategory.PROFILE_FACT,
            domain=MemoryDomain.GENERAL,
            evidence_text=evidence,
            source_thread_id="thread-1",
        )
        rule = validate_memory_candidate(paraphrased)
        assert not rule.ok, evidence
        assert rule.reasons


def _flight_memory(text, *, memory_id=None, condition=None, evidence=None):
    return TravelMemory(
        memory_id=memory_id,
        user_id="user-1",
        memory_text=text,
        category=MemoryCategory.FLIGHT_PREFERENCE,
        domain=MemoryDomain.FLIGHT,
        condition=condition,
        evidence_text=evidence or text,
        source_thread_id="thread-1",
    )


def test_trustmem_verifier_detects_coverage_preservation_and_faithfulness_failures():
    verifier = TrustMemInspiredMemoryVerifier(
        model="heuristic-trustmem-v1",
        prompt_version="test",
        coverage_threshold=0.8,
        preservation_threshold=0.9,
        faithfulness_threshold=0.95,
    )
    incomplete = _flight_memory(
        "ưu tiên business khi công tác",
        evidence="Tôi muốn business khi công tác và economy khi du lịch",
    )
    coverage = asyncio.run(
        verifier.evaluate(
            MemoryTransition(TransitionAction.INSERT, candidate=incomplete),
            MemoryVerifierContext(
                chunk=[
                    {
                        "type": "human",
                        "content": "Tôi muốn business khi công tác và economy khi du lịch",
                    }
                ],
                old_memories=[],
                new_memories=[incomplete],
            ),
        )
    )
    assert coverage.decision == "reject"
    assert coverage.dimensions["coverage"].score < 0.8

    old = _flight_memory(
        "ưu tiên economy khi du lịch",
        memory_id="old-1",
        condition="du lịch",
    )
    generalized = _flight_memory("luôn ưu tiên business")
    preservation = asyncio.run(
        verifier.evaluate(
            MemoryTransition(
                TransitionAction.SUPERSEDE,
                candidate=generalized,
                existing_memory_id="old-1",
            ),
            MemoryVerifierContext(
                chunk=[{"type": "human", "content": "Tôi muốn business khi công tác"}],
                old_memories=[old],
                new_memories=project_memory_state(
                    MemoryTransition(
                        TransitionAction.SUPERSEDE,
                        candidate=generalized,
                        existing_memory_id="old-1",
                    ),
                    [old],
                ),
            ),
        )
    )
    assert preservation.decision == "reject"
    assert preservation.dimensions["preservation"].score < 0.9

    tool_candidate = TravelMemory(
        memory_text="thích khách sạn gần ga",
        category=MemoryCategory.HOTEL_PREFERENCE,
        domain=MemoryDomain.HOTEL,
        evidence_text="search_id=abc total_results=3 hotel near station",
        source_thread_id="thread-1",
    )
    faithfulness = asyncio.run(
        verifier.evaluate(
            MemoryTransition(TransitionAction.INSERT, candidate=tool_candidate),
            MemoryVerifierContext(
                chunk=[
                    {
                        "type": "tool",
                        "content": "search_id=abc total_results=3 hotel near station",
                    }
                ],
                old_memories=[],
                new_memories=[tool_candidate],
            ),
        )
    )
    assert faithfulness.decision == "reject"
    assert faithfulness.dimensions["faithfulness"].score < 0.95


def test_trustmem_verifier_approval_dry_run_and_malformed_output():
    candidate = _flight_memory(
        "ưu tiên business khi công tác và economy khi du lịch",
        evidence="Tôi muốn business khi công tác và economy khi du lịch",
    )
    trustmem = TrustMemInspiredMemoryVerifier(
        model="heuristic-trustmem-v1",
        prompt_version="test",
        coverage_threshold=0.8,
        preservation_threshold=0.9,
        faithfulness_threshold=0.95,
    )
    approved = asyncio.run(
        trustmem.evaluate(
            MemoryTransition(TransitionAction.INSERT, candidate=candidate),
            MemoryVerifierContext(
                chunk=[
                    {
                        "type": "human",
                        "content": "Tôi muốn business khi công tác và economy khi du lịch",
                    }
                ],
                old_memories=[],
                new_memories=[candidate],
            ),
        )
    )
    assert approved.decision == "approve"
    assert approved.dimensions["faithfulness"].passed

    dry_run = build_memory_verifier(
        make_settings(long_term_memory_verifier="trustmem-dry-run")
    )
    dry_result = asyncio.run(
        dry_run.evaluate(
            MemoryTransition(TransitionAction.INSERT, candidate=candidate),
            MemoryVerifierContext(chunk=[], old_memories=[], new_memories=[candidate]),
        )
    )
    assert dry_result.decision == "approve"
    assert dry_result.mode == "trustmem-dry-run"

    malformed = TrustMemInspiredMemoryVerifier(
        model="bad",
        prompt_version="test",
        coverage_threshold=0.8,
        preservation_threshold=0.9,
        faithfulness_threshold=0.95,
        scorer=lambda transition, context: {
            "coverage": {"score": 1.2, "reason": "bad"},
            "preservation": {"score": 1.0, "reason": "ok"},
            "faithfulness": {"score": 1.0, "reason": "ok"},
        },
    )
    malformed_result = asyncio.run(
        malformed.evaluate(MemoryTransition(TransitionAction.INSERT, candidate=candidate))
    )
    assert malformed_result.decision == "retry"
    assert malformed_result.fallback_reason


def test_trustmem_timeout_error_has_labeled_fallback_reason():
    async def boom(_transition, _context):
        raise TimeoutError()

    verifier = TrustMemInspiredMemoryVerifier(
        model="gemini-2.5-flash",
        prompt_version="test",
        coverage_threshold=0.8,
        preservation_threshold=0.9,
        faithfulness_threshold=0.95,
        scorer=boom,
    )
    result = asyncio.run(
        verifier.evaluate(
            MemoryTransition(
                TransitionAction.INSERT,
                candidate=_flight_memory("ưu tiên bay thẳng"),
            )
        )
    )
    assert result.decision == "retry"
    assert result.fallback_reason
    assert "TimeoutError" in result.fallback_reason
    assert set(result.dimensions) == {"coverage", "preservation", "faithfulness"}


def test_trustmem_selects_llm_scorer_for_non_heuristic_model():
    heuristic = TrustMemInspiredMemoryVerifier(
        model="heuristic-trustmem-v1",
        prompt_version="test",
        coverage_threshold=0.8,
        preservation_threshold=0.9,
        faithfulness_threshold=0.95,
    )
    llm = TrustMemInspiredMemoryVerifier(
        model="gemini-2.5-flash",
        prompt_version="test",
        coverage_threshold=0.8,
        preservation_threshold=0.9,
        faithfulness_threshold=0.95,
    )
    assert heuristic._scorer == heuristic._heuristic_scores
    assert llm._scorer == llm._llm_scores


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

    async def commit_supersede(self, *, existing_memory_id: str, new_memory):
        self.superseded.append(existing_memory_id)
        self.inserted.append(new_memory)
        return "inserted-1"

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

    trustmem_repo = CommitRepo()
    trustmem_adapter = MemoryCommitAdapter(
        repository=trustmem_repo,
        verifier=build_memory_verifier(make_settings(long_term_memory_verifier="trustmem")),
    )
    context = MemoryVerifierContext(
        chunk=[{"type": "human", "content": "Tôi ưu tiên bay thẳng"}],
        old_memories=[],
        new_memories=[candidate],
    )
    asyncio.run(
        trustmem_adapter.verify_and_commit(
            transition=MemoryTransition(TransitionAction.INSERT, candidate=candidate),
            user_id="user-1",
            thread_id="thread-1",
            verifier_context=context,
        )
    )
    verifier_result = trustmem_repo.audits[-1]["verifier_result"]
    assert verifier_result["mode"] == "trustmem"
    assert set(verifier_result["dimensions"]) == {
        "coverage",
        "preservation",
        "faithfulness",
    }

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


def test_langmem_extractor_skips_assistant_only_turn():
    manager = FakeLangMemManager(
        [
            type(
                "Extracted",
                (),
                {
                    "content": LangMemTravelMemory(
                        memory_text="thích resort yên tĩnh",
                        category=MemoryCategory.HOTEL_PREFERENCE,
                        domain=MemoryDomain.HOTEL,
                        evidence_text="thích resort yên tĩnh",
                    )
                },
            )()
        ]
    )
    extractor = LangMemCandidateExtractor(manager=manager)
    candidates = asyncio.run(
        extractor.extract(
            [
                {
                    "type": "assistant",
                    "content": "Tôi sẽ ghi nhớ rằng bạn thích resort yên tĩnh.",
                }
            ],
            user_id="user-1",
            thread_id="thread-1",
        )
    )
    assert candidates == []
    assert manager.inputs == []


def test_validate_rejects_hedged_neu_tien_and_neu_duoc():
    for evidence in (
        "Nếu tiện thì tôi thích khách sạn gần biển",
        "Nếu được thì ưu tiên bay buổi sáng",
        "Có lẽ tôi thích resort yên tĩnh",
        "Tôi nghĩ tôi thích resort gần hồ",
        "Có vẻ tôi ưu tiên bay sáng",
        "Dường như tôi thích xe hybrid",
        "Khả năng là tôi thích museum tour",
        "E rằng tôi ưu tiên trả lời ngắn",
    ):
        candidate = TravelMemory(
            memory_text="thích khách sạn gần biển",
            category=MemoryCategory.HOTEL_PREFERENCE,
            domain=MemoryDomain.HOTEL,
            evidence_text=evidence,
            source_thread_id="thread-1",
        )
        rule = validate_memory_candidate(candidate)
        assert not rule.ok, evidence
        assert any("ambiguous" in reason for reason in rule.reasons)


def test_langmem_normalizer_requires_user_grounding_when_provided():
    outputs = [
        {
            "memory_text": "thích resort yên tĩnh",
            "category": "hotel_preference",
            "domain": "hotel",
            "evidence_text": "thích resort yên tĩnh",
        }
    ]
    rejected = normalize_langmem_outputs(
        outputs,
        user_id="user-1",
        thread_id="thread-1",
        fallback_evidence="",
        user_texts=["Để xem thêm đã"],
    )
    assert rejected == []
    accepted = normalize_langmem_outputs(
        outputs,
        user_id="user-1",
        thread_id="thread-1",
        fallback_evidence="Tôi thích resort yên tĩnh",
        user_texts=["Tôi thích resort yên tĩnh"],
    )
    assert len(accepted) == 1


def test_clean_memory_text_normalizes_profile_address_forms():
    assert _clean_memory_text("Gọi tôi là anh Khoa") == "anh Khoa"
    assert _clean_memory_text("Gọi tôi là chị Mai") == "chị Mai"
    assert _clean_memory_text("Tôi thích được gọi là chị Lan") == "được gọi là chị Lan"
    assert _clean_memory_text("Thích được gọi là chị Lan") == "được gọi là chị Lan"


def test_classify_memory_keeps_short_honorific_as_profile():
    assert classify_memory("anh Khoa") == (
        MemoryCategory.PROFILE_FACT,
        MemoryDomain.GENERAL,
    )
    assert classify_memory("được gọi là chị Lan") == (
        MemoryCategory.PROFILE_FACT,
        MemoryDomain.GENERAL,
    )


def test_profile_address_extracts_to_gold_short_form():
    candidates = extract_candidate_memories(
        [{"type": "human", "content": "Gọi tôi là anh Khoa"}],
        user_id="user-1",
        thread_id="thread-1",
    )
    assert len(candidates) == 1
    assert candidates[0].memory_text == "anh Khoa"
    assert candidates[0].category == MemoryCategory.PROFILE_FACT


def test_langmem_normalizer_cleans_profile_address_wording():
    candidates = normalize_langmem_outputs(
        [
            {
                "memory_text": "Gọi tôi là anh Tuấn",
                "category": "profile_fact",
                "domain": "general",
                "evidence_text": "Gọi tôi là anh Tuấn",
            },
            {
                "memory_text": "Thích được gọi là chị Lan",
                "category": "profile_fact",
                "domain": "general",
                "evidence_text": "Tôi thích được gọi là chị Lan",
            },
        ],
        user_id="user-1",
        thread_id="thread-1",
        fallback_evidence="fallback",
    )
    assert [c.memory_text for c in candidates] == ["anh Tuấn", "được gọi là chị Lan"]


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
