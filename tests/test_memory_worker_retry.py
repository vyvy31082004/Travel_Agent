import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memory.commit import CommitResult
from memory.consolidation import MemoryTransition, TransitionAction
from memory.long_term import MemoryCategory, MemoryDomain, TravelMemory
from memory.worker import MemoryWorker
from settings import Settings


def make_settings(**overrides):
    values = dict(
        database_url="postgresql://user:pass@localhost/db",
        cookie_secret="secret",
        long_term_memory_transition_path="lexical",
        long_term_memory_worker_retry_limit=3,
    )
    values.update(overrides)
    return Settings(**values)


def _candidate():
    return TravelMemory(
        user_id="user-1",
        memory_text="ưu tiên bay thẳng",
        category=MemoryCategory.FLIGHT_PREFERENCE,
        domain=MemoryDomain.FLIGHT,
        evidence_text="Tôi ưu tiên bay thẳng",
        source_thread_id="thread-1",
    )


class _StubExtractor:
    def __init__(self, candidates):
        self._candidates = candidates

    async def extract(self, messages, *, user_id, thread_id, existing_active):
        return list(self._candidates)


class _StubCommitAdapter:
    def __init__(self, decision):
        self._decision = decision
        self.calls = 0

    async def verify_and_commit(self, **kwargs):
        self.calls += 1
        return CommitResult(decision=self._decision, affected_memory_ids=[])


class _HarnessWorker(MemoryWorker):
    """MemoryWorker with DB-facing methods stubbed for pure logic testing."""

    def __init__(self, *, settings, extractor, commit_adapter):
        # Bypass MemoryWorker.__init__ (which builds judges / needs a pool).
        self._pool = None
        self._settings = settings
        self._repository = None
        self._commit_adapter = commit_adapter
        self._extractor = extractor
        self._embedding_service = None
        self._scope_judge = None
        self._relation_judge = None
        self.mark_job_calls = []
        self.mark_failed_calls = []

    async def _load_existing(self, user_id):
        return []

    async def _mark_job(self, job_id, status):
        self.mark_job_calls.append((job_id, status))

    async def _mark_job_failed(self, job_id, error_summary):
        self.mark_failed_calls.append((job_id, error_summary))


def _job():
    return {
        "job_id": "11111111-1111-1111-1111-111111111111",
        "user_id": "user-1",
        "thread_id": "thread-1",
        "messages": [{"type": "human", "content": "Tôi ưu tiên bay thẳng"}],
        "attempts": 1,
    }


def test_verifier_retry_keeps_job_retryable_not_completed():
    adapter = _StubCommitAdapter(decision="retry")
    worker = _HarnessWorker(
        settings=make_settings(),
        extractor=_StubExtractor([_candidate()]),
        commit_adapter=adapter,
    )
    result = asyncio.run(worker._process_claimed_job(_job()))

    # The candidate was surfaced to the verifier but not dropped as completed.
    assert adapter.calls == 1
    assert result.status == "failed"
    assert worker.mark_job_calls == []  # never marked completed
    assert len(worker.mark_failed_calls) == 1
    _, summary = worker.mark_failed_calls[0]
    assert "retry" in summary.lower()


def test_approved_candidate_completes_job():
    adapter = _StubCommitAdapter(decision="approve")
    worker = _HarnessWorker(
        settings=make_settings(),
        extractor=_StubExtractor([_candidate()]),
        commit_adapter=adapter,
    )
    result = asyncio.run(worker._process_claimed_job(_job()))

    assert result.status == "completed"
    assert worker.mark_job_calls == [
        ("11111111-1111-1111-1111-111111111111", "completed")
    ]
    assert worker.mark_failed_calls == []
