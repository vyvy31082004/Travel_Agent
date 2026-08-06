from __future__ import annotations

from dataclasses import asdict, dataclass, field

from memory.consolidation import MemoryTransition, TransitionAction
from memory.verifier import MemoryVerifier, VerifierResult
from repositories.long_term_memory import LongTermMemoryRepository


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
    ) -> None:
        self._repository = repository
        self._verifier = verifier

    async def verify_and_commit(
        self,
        *,
        transition: MemoryTransition,
        user_id: str,
        thread_id: str | None,
        job_id: str | None = None,
    ) -> CommitResult:
        judgment = await self._verifier.evaluate(transition)
        affected: list[str] = []
        decision = judgment.decision

        if judgment.decision == "approve" and transition.candidate is not None:
            if transition.action == TransitionAction.INSERT:
                affected.append(await self._repository.insert_memory(transition.candidate))
            elif transition.action == TransitionAction.SUPERSEDE:
                if transition.existing_memory_id:
                    await self._repository.mark_memory_superseded(
                        transition.existing_memory_id
                    )
                    affected.append(transition.existing_memory_id)
                affected.append(await self._repository.insert_memory(transition.candidate))
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


def _transition_to_dict(transition: MemoryTransition) -> dict:
    return {
        "action": str(transition.action),
        "candidate": transition.candidate.to_record() if transition.candidate else None,
        "existing_memory_id": transition.existing_memory_id,
        "reasons": transition.reasons,
    }


def _verifier_to_dict(result: VerifierResult) -> dict:
    return {
        "decision": result.decision,
        "reasons": result.reasons,
        "model": result.model,
        "prompt_version": result.prompt_version,
    }
