from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from memory.consolidation import MemoryTransition, TransitionAction


@dataclass(frozen=True)
class VerifierResult:
    decision: str
    reasons: list[str] = field(default_factory=list)
    model: str = "deterministic"
    prompt_version: str = "memory-verifier-v1"

    @property
    def approved(self) -> bool:
        return self.decision in {"approve", "noop"}


class MemoryVerifier(Protocol):
    async def evaluate(self, transition: MemoryTransition) -> VerifierResult:
        """Evaluate a non-trivial memory transition."""


class DeterministicMemoryVerifier:
    """Conservative verifier baseline.

    This keeps the implementation stable until an LLM verifier prompt/model is
    explicitly configured and tested. It approves inserts/no-ops that passed
    deterministic rules, and requires human/future LLM review for supersessions.
    """

    async def evaluate(self, transition: MemoryTransition) -> VerifierResult:
        if transition.action == TransitionAction.REJECT:
            return VerifierResult("reject", transition.reasons)
        if transition.action == TransitionAction.NOOP:
            return VerifierResult("noop", transition.reasons)
        if transition.action == TransitionAction.SUPERSEDE:
            return VerifierResult(
                "retry",
                [
                    "supersession requires configured LLM verifier or explicit review",
                    *transition.reasons,
                ],
            )
        if transition.action == TransitionAction.INSERT:
            return VerifierResult("approve", transition.reasons)
        return VerifierResult("reject", [f"unsupported action: {transition.action}"])
