from __future__ import annotations

import logging
from dataclasses import dataclass, field

from memory.consolidation import MemoryTransition, TransitionAction
from memory.embeddings import MemoryEmbeddingService, memory_content_hash
from memory.verifier import MemoryVerifier, MemoryVerifierContext, VerifierResult
from repositories.long_term_memory import (
    LongTermMemoryRepository,
    MemoryEmbeddingRecord,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommitResult:
    decision: str
    affected_memory_ids: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


class MemoryCommitAdapter:
    def __init__(
        self,
        *,
        repository: LongTermMemoryRepository,
        verifier: MemoryVerifier,
        embedding_service: MemoryEmbeddingService | None = None,
    ) -> None:
        self._repository = repository
        self._verifier = verifier
        self._embedding_service = embedding_service

    async def verify_and_commit(
        self,
        *,
        transition: MemoryTransition,
        user_id: str,
        thread_id: str | None,
        job_id: str | None = None,
        verifier_context: MemoryVerifierContext | None = None,
    ) -> CommitResult:
        judgment = await self._verifier.evaluate(transition, verifier_context)
        affected: list[str] = []
        decision = judgment.decision

        if judgment.decision == "approve" and transition.candidate is not None:
            if transition.action == TransitionAction.INSERT:
                memory_id = await self._repository.insert_memory(transition.candidate)
                affected.append(memory_id)
                await self._embed_committed_memory(memory_id, transition.candidate)
            elif transition.action == TransitionAction.SUPERSEDE:
                if transition.existing_memory_id:
                    await self._repository.mark_memory_superseded(
                        transition.existing_memory_id
                    )
                    affected.append(transition.existing_memory_id)
                memory_id = await self._repository.insert_memory(transition.candidate)
                affected.append(memory_id)
                await self._embed_committed_memory(memory_id, transition.candidate)
            elif transition.action == TransitionAction.NOOP:
                decision = "noop"
                if transition.existing_memory_id:
                    affected.append(transition.existing_memory_id)
        elif judgment.decision == "noop":
            if transition.existing_memory_id:
                affected.append(transition.existing_memory_id)
        else:
            decision = judgment.decision

        await self._repository.write_audit_record(
            job_id=job_id,
            user_id=user_id,
            thread_id=thread_id,
            decision=decision,
            proposed_transition=_transition_to_dict(transition),
            rule_result={"reasons": transition.reasons},
            verifier_result=_verifier_to_dict(judgment),
            affected_memory_ids=affected,
        )
        return CommitResult(
            decision=decision,
            affected_memory_ids=affected,
            reasons=[*transition.reasons, *judgment.reasons],
        )

    async def _embed_committed_memory(self, memory_id: str, memory) -> None:
        if self._embedding_service is None:
            return
        try:
            embedding = await self._embedding_service.embed_memory(memory)
            await self._repository.upsert_memory_embedding(
                MemoryEmbeddingRecord(
                    memory_id=memory_id,
                    embedding=embedding,
                    embedding_model=self._embedding_service.model,
                    embedding_dims=self._embedding_service.dims,
                    content_hash=memory_content_hash(
                        memory,
                        model=self._embedding_service.model,
                    ),
                )
            )
        except Exception as exc:  # Embedding must not roll back approved memory commit.
            logger.warning("failed to embed committed memory %s: %s", memory_id, exc)


def _transition_to_dict(transition: MemoryTransition) -> dict:
    return {
        "action": str(transition.action),
        "candidate": transition.candidate.to_record() if transition.candidate else None,
        "existing_memory_id": transition.existing_memory_id,
        "reasons": transition.reasons,
    }


def _verifier_to_dict(result: VerifierResult) -> dict:
    return result.to_dict()
