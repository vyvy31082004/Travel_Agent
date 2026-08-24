from __future__ import annotations

from dataclasses import replace
from typing import Any, Sequence
from uuid import uuid4

from memory.long_term import MemoryFamily, MemoryStatus, TravelMemory
from repositories.long_term_memory import (
    MemoryEmbeddingRecord,
    MemorySearchFilters,
    NoopLongTermMemoryRepository,
)


class InMemoryLongTermMemoryRepository(NoopLongTermMemoryRepository):
    """Seedable store for offline transition/retrieval evaluation."""

    def __init__(self, memories: Sequence[TravelMemory] = ()) -> None:
        self.memories: dict[str, TravelMemory] = {}
        for memory in memories:
            memory_id = memory.memory_id or str(uuid4())
            self.memories[memory_id] = replace(memory, memory_id=memory_id)

    async def search_active_memories(
        self, filters: MemorySearchFilters
    ) -> list[TravelMemory]:
        matched: list[TravelMemory] = []
        query = (filters.query or "").casefold()
        for memory in self.memories.values():
            if memory.user_id != filters.user_id:
                continue
            if MemoryFamily(memory.family) not in filters.families:
                continue
            if MemoryStatus(memory.status) != MemoryStatus.ACTIVE:
                continue
            if not memory.is_active:
                continue
            if query:
                blob = " ".join(
                    part
                    for part in (
                        memory.memory_text,
                        memory.condition or "",
                        memory.evidence_text,
                    )
                ).casefold()
                if query not in blob and not any(
                    term and term in blob for term in query.split()
                ):
                    continue
            matched.append(memory)
        return matched[: filters.limit]

    async def insert_memory(self, memory: TravelMemory) -> str:
        memory_id = memory.memory_id or str(uuid4())
        stored = replace(memory, memory_id=memory_id)
        self.memories[memory_id] = stored
        return memory_id

    async def mark_memory_superseded(self, memory_id: str) -> None:
        current = self.memories.get(memory_id)
        if current is None:
            return
        self.memories[memory_id] = replace(current, status=MemoryStatus.SUPERSEDED)

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

    async def upsert_memory_embedding(self, record: MemoryEmbeddingRecord) -> None:
        return None
