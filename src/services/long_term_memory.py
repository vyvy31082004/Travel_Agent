from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence

from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig

from memory.embeddings import MemoryEmbeddingService
from memory.applicability import (
    ApplicabilityJudge,
    build_applicability_judge,
    format_applied_context,
    partition_judgments,
)
from memory.task_router import ActionInferrer, build_action_inferrer
from memory.long_term import (
    MemoryDomain,
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


@dataclass(frozen=True)
class DomainRecallResult(RecallResult):
    domain_action: str = "general"
    domain_soft_memory_context: str = ""
    applicability: list[dict[str, Any]] = field(default_factory=list)


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
        action_inferrer: ActionInferrer | None = None,
        applicability_judge: ApplicabilityJudge | None = None,
    ) -> None:
        self._settings = settings
        self._repository = repository or NoopLongTermMemoryRepository()
        self._processor = processor
        self._embedding_service = embedding_service
        self._action_inferrer = action_inferrer
        self._applicability_judge = applicability_judge

    async def recall(
        self,
        *,
        user_id: str | None,
        query: str | None,
        families: Sequence[MemoryFamily] | None = None,
        domains: Sequence[str] | None = None,
    ) -> RecallResult:
        if not self._settings.long_term_memory_recall_enabled:
            return RecallResult()
        user = (user_id or "").strip()
        text = (query or "").strip()
        if not user or not text:
            return RecallResult()

        selected_families = tuple(families or (MemoryFamily.TRAVEL_PREFERENCES,))
        domain_filter = tuple(domains) if domains else None
        filters = MemorySearchFilters(
            user_id=user,
            families=selected_families,
            query=text,
            limit=self._settings.long_term_memory_recall_limit,
            domains=domain_filter,
        )
        memories = await self._recall_memories(filters, text)
        lines = [format_memory_for_prompt(memory) for memory in memories]
        ids = [memory.memory_id for memory in memories if memory.memory_id]
        return RecallResult(
            memory_context="\n".join(lines),
            recalled_memory_ids=ids,
            memories=memories,
        )

    async def recall_global(
        self,
        *,
        user_id: str | None,
        query: str | None,
    ) -> RecallResult:
        if not self._settings.long_term_memory_recall_enabled:
            return RecallResult()
        user = (user_id or "").strip()
        text = (query or "").strip()
        if not user or not text:
            return RecallResult()

        limit = self._settings.long_term_memory_recall_limit
        profile_interaction = await self._recall_memories(
            MemorySearchFilters(
                user_id=user,
                families=(
                    MemoryFamily.PROFILE_FACTS,
                    MemoryFamily.INTERACTION_RULES,
                ),
                query=text,
                limit=limit,
            ),
            text,
        )
        general_prefs = await self._recall_memories(
            MemorySearchFilters(
                user_id=user,
                families=(MemoryFamily.TRAVEL_PREFERENCES,),
                query=text,
                limit=limit,
                domains=(MemoryDomain.GENERAL.value,),
            ),
            text,
        )
        return self._merge_recall_results(profile_interaction, general_prefs, limit=limit)

    async def fetch_domain_candidates(
        self,
        *,
        user_id: str | None,
        domain: str,
    ) -> list[TravelMemory]:
        if not self._settings.long_term_memory_recall_enabled:
            return []
        user = (user_id or "").strip()
        domain_value = (domain or "").strip()
        if not user or not domain_value:
            return []
        memories = await self._repository.fetch_active_domain_memories(
            user_id=user,
            domain=domain_value,
            limit=self._settings.long_term_memory_domain_candidate_limit,
        )
        return [memory for memory in memories if memory.is_active]

    async def recall_domain_with_applicability(
        self,
        *,
        user_id: str | None,
        query: str | None,
        domain: str,
        domain_action: str | None = None,
        domain_state: dict[str, Any] | None = None,
        llm=None,
    ) -> DomainRecallResult:
        if not self._settings.long_term_memory_recall_enabled:
            return DomainRecallResult()
        user = (user_id or "").strip()
        text = (query or "").strip()
        domain_value = (domain or "").strip()
        state = dict(domain_state or {})
        if not user or not text or not domain_value:
            return DomainRecallResult()

        candidates = await self.fetch_domain_candidates(user_id=user, domain=domain_value)
        inferrer = self._action_inferrer or build_action_inferrer(
            llm=llm,
            use_llm=self._settings.long_term_memory_action_inference_enabled,
        )
        action = domain_action or await inferrer.infer_domain_action(
            user_query=text,
            domain=domain_value,
            domain_state=state,
        )
        if self._settings.long_term_memory_applicability_judge_enabled:
            judge = self._applicability_judge or build_applicability_judge(
                llm=llm,
                use_llm=llm is not None,
                batch_size=self._settings.long_term_memory_applicability_batch_size,
            )
            judgments = await judge.judge_batch(
                user_query=text,
                domain=domain_value,
                domain_action=action,
                domain_state=state,
                candidates=candidates,
            )
        else:
            from memory.applicability import ApplicabilityJudgment, ApplicabilityLabel

            judgments = [
                ApplicabilityJudgment(
                    memory_id=str(memory.memory_id or ""),
                    label=ApplicabilityLabel.APPLY,
                    confidence=1.0,
                    reason="judge disabled",
                )
                for memory in candidates
            ]

        apply_memories, uncertain_memories, audit = partition_judgments(
            candidates, judgments
        )
        apply_context = format_applied_context(apply_memories)
        soft_context = format_applied_context(uncertain_memories)
        recalled_ids = [
            memory.memory_id
            for memory in (*apply_memories, *uncertain_memories)
            if memory.memory_id
        ]
        return DomainRecallResult(
            memory_context=apply_context,
            domain_soft_memory_context=soft_context,
            recalled_memory_ids=recalled_ids,
            memories=apply_memories + uncertain_memories,
            domain_action=action,
            applicability=[
                {
                    "memory_id": item.memory_id,
                    "label": str(item.label),
                    "confidence": item.confidence,
                    "reason": item.reason,
                }
                for item in audit
            ],
        )

    async def recall_domain(
        self,
        *,
        user_id: str | None,
        query: str | None,
        domain: str,
    ) -> RecallResult:
        domain_value = (domain or "").strip()
        if not domain_value:
            return RecallResult()
        return await self.recall(
            user_id=user_id,
            query=query,
            families=(MemoryFamily.TRAVEL_PREFERENCES,),
            domains=(domain_value,),
        )

    @staticmethod
    def _merge_recall_results(
        *groups: list[TravelMemory],
        limit: int,
    ) -> RecallResult:
        seen: set[str] = set()
        merged: list[TravelMemory] = []
        for group in groups:
            for memory in group:
                memory_id = memory.memory_id
                if not memory_id or memory_id in seen:
                    continue
                seen.add(memory_id)
                merged.append(memory)
                if len(merged) >= limit:
                    break
            if len(merged) >= limit:
                break
        lines = [format_memory_for_prompt(memory) for memory in merged]
        ids = [memory.memory_id for memory in merged if memory.memory_id]
        return RecallResult(
            memory_context="\n".join(lines),
            recalled_memory_ids=ids,
            memories=merged,
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
                active = [memory for memory in memories if memory.is_active][
                    : self._settings.long_term_memory_recall_limit
                ]
                if active:
                    return active
            except Exception as exc:
                logger.warning("vector memory recall failed; falling back: %s", exc)
                if not self._settings.long_term_memory_vector_fallback_enabled:
                    raise

        memories = [
            memory
            for memory in await self._repository.search_active_memories(filters)
            if memory.is_active
        ]
        # Lexical ILIKE misses when preference wording differs from the user
        # question ("ghét biển" vs "khách sạn Nha Trang"). Fall back to recent
        # active memories filtered only by user / family / status.
        if not memories and filters.query:
            fallback = MemorySearchFilters(
                user_id=filters.user_id,
                families=filters.families,
                query=None,
                limit=filters.limit,
                domains=filters.domains,
            )
            memories = [
                memory
                for memory in await self._repository.search_active_memories(fallback)
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
