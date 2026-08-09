from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence

from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig

from memory.embeddings import MemoryEmbeddingService
from memory.long_term import (
    MemoryFamily,
    TravelMemory,
    format_memory_for_prompt,
)
from repositories.long_term_memory import (
    LongTermMemoryRepository,
    MemoryJobRef,
    MemorySearchFilters,
    NoopLongTermMemoryRepository,
)
from settings import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecallResult:
    memory_context: str = ""
    recalled_memory_ids: list[str] = field(default_factory=list)
    memories: list[TravelMemory] = field(default_factory=list)


class MemoryJobProcessor(Protocol):
    async def process_job(self, job_id: str) -> None:
        """Process one memory job for local/prototype synchronous finalize mode."""


class MemoryService:
    def __init__(
        self,
        *,
        settings: Settings,
        repository: LongTermMemoryRepository | None = None,
        processor: MemoryJobProcessor | None = None,
        embedding_service: MemoryEmbeddingService | None = None,
    ) -> None:
        self._settings = settings
        self._repository = repository or NoopLongTermMemoryRepository()
        self._processor = processor
        self._embedding_service = embedding_service

    async def recall(
        self,
        *,
        user_id: str | None,
        query: str | None,
        families: Sequence[MemoryFamily] | None = None,
    ) -> RecallResult:
        if not self._settings.long_term_memory_recall_enabled:
            return RecallResult()
        user = (user_id or "").strip()
        text = (query or "").strip()
        if not user or not text:
            return RecallResult()

        selected_families = tuple(families or (MemoryFamily.TRAVEL_PREFERENCES,))
        filters = MemorySearchFilters(
            user_id=user,
            families=selected_families,
            query=text,
            limit=self._settings.long_term_memory_recall_limit,
        )
        memories = await self._recall_memories(filters, text)
        lines = [format_memory_for_prompt(memory) for memory in memories]
        ids = [memory.memory_id for memory in memories if memory.memory_id]
        return RecallResult(
            memory_context="\n".join(lines),
            recalled_memory_ids=ids,
            memories=memories,
        )

    async def _recall_memories(
        self,
        filters: MemorySearchFilters,
        query: str,
    ) -> list[TravelMemory]:
        if (
            self._settings.long_term_memory_vector_search_enabled
            and self._embedding_service is not None
        ):
            try:
                query_embedding = await self._embedding_service.embed_query(query)
                memories = await self._repository.semantic_search_active_memories(
                    filters,
                    query_embedding=query_embedding,
                    embedding_model=self._embedding_service.model,
                    embedding_dims=self._embedding_service.dims,
                    distance_threshold=(
                        self._settings.long_term_memory_vector_distance_threshold
                    ),
                )
                return [memory for memory in memories if memory.is_active][
                    : self._settings.long_term_memory_recall_limit
                ]
            except Exception as exc:
                logger.warning("vector memory recall failed; falling back: %s", exc)
                if not self._settings.long_term_memory_vector_fallback_enabled:
                    raise
        memories = [
            memory
            for memory in await self._repository.search_active_memories(filters)
            if memory.is_active
        ]
        return memories[: self._settings.long_term_memory_recall_limit]

    async def enqueue_final_turn(
        self,
        *,
        user_id: str | None,
        thread_id: str | None,
        final_message_id: str | None,
        checkpoint_id: str | None,
        messages: Sequence[BaseMessage] | Sequence[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> MemoryJobRef | None:
        if not self._settings.long_term_memory_write_enabled:
            return None
        user = (user_id or "").strip()
        thread = (thread_id or "").strip()
        if not user or not thread:
            return None
        idempotency_key = memory_job_idempotency_key(
            user_id=user,
            thread_id=thread,
            final_message_id=final_message_id,
            checkpoint_id=checkpoint_id,
        )
        job = await self._repository.enqueue_memory_job(
            user_id=user,
            thread_id=thread,
            idempotency_key=idempotency_key,
            final_message_id=final_message_id,
            checkpoint_id=checkpoint_id,
            messages=[serialize_message(message) for message in messages],
            metadata=metadata or {},
        )
        if (
            self._settings.long_term_memory_sync_finalize
            and self._processor is not None
            and job.created
            and job.job_id != "noop"
        ):
            await self._processor.process_job(job.job_id)
        return job


def memory_job_idempotency_key(
    *,
    user_id: str,
    thread_id: str,
    final_message_id: str | None,
    checkpoint_id: str | None,
) -> str:
    identity = final_message_id or checkpoint_id
    if not identity:
        identity = "unknown-final-message"
    raw = f"{user_id}:{thread_id}:{identity}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def serialize_message(message: BaseMessage | dict[str, Any]) -> dict[str, Any]:
    if isinstance(message, dict):
        return dict(message)
    return {
        "type": getattr(message, "type", message.__class__.__name__),
        "content": getattr(message, "content", ""),
        "id": getattr(message, "id", None),
        "tool_call_id": getattr(message, "tool_call_id", None),
        "tool_calls": getattr(message, "tool_calls", None),
    }


def config_user_thread(config: RunnableConfig | None) -> tuple[str | None, str | None]:
    configurable = (config or {}).get("configurable") or {}
    user_id = configurable.get("user_id")
    thread_id = configurable.get("thread_id")
    return (str(user_id) if user_id else None, str(thread_id) if thread_id else None)
