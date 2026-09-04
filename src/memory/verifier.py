from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field, replace
from typing import Any, Protocol, Sequence

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field

from memory.consolidation import MemoryTransition, TransitionAction
from memory.long_term import MemoryStatus, TravelMemory
from settings import Settings

logger = logging.getLogger(__name__)

TRUSTMEM_SYSTEM_PROMPT = """You are a frozen TrustMem-style verifier for a travel assistant.
Score a proposed local memory transition z_t = (chunk, M_old, actions, M_new).

Return scores in [0, 1] with short reasons.

The payload may include sibling_candidates: other memory candidates from the same
finalize job that are proposed alongside this candidate (atomic split of one
user utterance into multiple memories). Treat THIS candidate + sibling_candidates
as one collective write set for coverage.

Each memory in M_old / M_new includes status. For action=supersede, M_new correctly
keeps the replaced memory with status=superseded and adds the candidate as active.
That is successful replacement — do NOT penalize preservation for seeing the old
text still listed when its status is superseded. Only penalize if a contradicted
old preference remains status=active, or if valid unrelated memories were deleted /
distorted / over-generalized / merged with lost conditions.

Dimensions:
- coverage: durable user facts/preferences in the chunk are collectively preserved
  across THIS candidate AND sibling_candidates. A candidate may cover only part of
  the chunk when siblings cover the remainder. Penalize coverage only if a durable
  fact is missing from BOTH this candidate AND all siblings.
- preservation: valid old memories are not incorrectly deleted, distorted, over-generalized, or merged with lost conditions (e.g. business vs leisure, family vs solo).
  Correct supersede (old status=superseded + new active preference) preserves history
  and should score high.
- faithfulness: new/changed memory is supported by the user's own evidence in the chunk or by valid M_old. Tool/API search results alone are not user preferences.
  An atomic split that states only one supported attribute (with other attributes in
  sibling_candidates) is faithful — do not treat omitted sibling attributes as
  over-generalization.

Be conservative. If evidence is missing or the candidate looks like tool output, lower faithfulness sharply."""


class TrustMemLlmScores(BaseModel):
    coverage_score: float = Field(ge=0, le=1)
    coverage_reason: str
    preservation_score: float = Field(ge=0, le=1)
    preservation_reason: str
    faithfulness_score: float = Field(ge=0, le=1)
    faithfulness_reason: str

    def to_dimension_dict(self) -> dict[str, dict[str, Any]]:
        return {
            "coverage": {
                "score": self.coverage_score,
                "reason": self.coverage_reason,
            },
            "preservation": {
                "score": self.preservation_score,
                "reason": self.preservation_reason,
            },
            "faithfulness": {
                "score": self.faithfulness_score,
                "reason": self.faithfulness_reason,
            },
        }


@dataclass(frozen=True)
class VerifierDimensionScore:
    score: float
    reason: str
    threshold: float

    def __post_init__(self) -> None:
        value = float(self.score)
        if not 0 <= value <= 1:
            raise ValueError("verifier score must be between 0 and 1")
        object.__setattr__(self, "score", value)
        object.__setattr__(self, "reason", self.reason.strip() or "no reason provided")

    @property
    def passed(self) -> bool:
        return self.score >= self.threshold

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "reason": self.reason,
            "threshold": self.threshold,
            "passed": self.passed,
        }


@dataclass(frozen=True)
class MemoryVerifierContext:
    chunk: Sequence[dict[str, Any]] = ()
    old_memories: Sequence[TravelMemory] = ()
    new_memories: Sequence[TravelMemory] = ()
    sibling_candidates: Sequence[TravelMemory] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk": [dict(message) for message in self.chunk],
            "M_old": [memory.to_record() for memory in self.old_memories],
            "M_new": [memory.to_record() for memory in self.new_memories],
            "sibling_candidates": [
                memory.to_record() for memory in self.sibling_candidates
            ],
        }


@dataclass(frozen=True)
class VerifierResult:
    decision: str
    reasons: list[str] = field(default_factory=list)
    model: str = "deterministic"
    prompt_version: str = "memory-verifier-v1"
    mode: str = "deterministic"
    dimensions: dict[str, VerifierDimensionScore] = field(default_factory=dict)
    fallback_reason: str | None = None

    @property
    def approved(self) -> bool:
        return self.decision in {"approve", "noop"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "reasons": self.reasons,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "mode": self.mode,
            "dimensions": {
                name: score.to_dict() for name, score in self.dimensions.items()
            },
            "fallback_reason": self.fallback_reason,
        }


class MemoryVerifier(Protocol):
    async def evaluate(
        self,
        transition: MemoryTransition,
        context: MemoryVerifierContext | None = None,
    ) -> VerifierResult:
        """Evaluate a non-trivial memory transition."""


class DeterministicMemoryVerifier:
    """Conservative verifier baseline."""

    async def evaluate(
        self,
        transition: MemoryTransition,
        context: MemoryVerifierContext | None = None,
    ) -> VerifierResult:
        if transition.action == TransitionAction.REJECT:
            return VerifierResult("reject", transition.reasons)
        if transition.action == TransitionAction.NOOP:
            return VerifierResult("noop", transition.reasons)
        if transition.action == TransitionAction.SUPERSEDE:
            return VerifierResult("approve", transition.reasons)
        if transition.action == TransitionAction.INSERT:
            return VerifierResult("approve", transition.reasons)
        return VerifierResult("reject", [f"unsupported action: {transition.action}"])


class TrustMemInspiredMemoryVerifier:
    def __init__(
        self,
        *,
        model: str,
        prompt_version: str,
        coverage_threshold: float,
        preservation_threshold: float,
        faithfulness_threshold: float,
        timeout_seconds: int = 30,
        scorer: Any | None = None,
        fallback: MemoryVerifier | None = None,
    ) -> None:
        self._model = model
        self._prompt_version = prompt_version
        self._coverage_threshold = coverage_threshold
        self._preservation_threshold = preservation_threshold
        self._faithfulness_threshold = faithfulness_threshold
        self._timeout_seconds = timeout_seconds
        self._fallback = fallback or DeterministicMemoryVerifier()
        if scorer is not None:
            self._scorer = scorer
        elif _uses_heuristic_model(model):
            self._scorer = self._heuristic_scores
        else:
            self._scorer = self._llm_scores

    async def evaluate(
        self,
        transition: MemoryTransition,
        context: MemoryVerifierContext | None = None,
    ) -> VerifierResult:
        if transition.action == TransitionAction.REJECT:
            return VerifierResult(
                "reject",
                transition.reasons,
                model=self._model,
                prompt_version=self._prompt_version,
                mode="trustmem",
            )
        if transition.action == TransitionAction.NOOP:
            return VerifierResult(
                "noop",
                transition.reasons,
                model=self._model,
                prompt_version=self._prompt_version,
                mode="trustmem",
                dimensions=self._passing_dimensions("no-op preserves existing memory"),
            )
        try:
            dimensions = await asyncio.wait_for(
                _maybe_await(self._scorer(transition, context)),
                timeout=self._timeout_seconds,
            )
            dimensions = self._normalize_dimensions(dimensions)
        except Exception as exc:
            fallback_reason = _format_verifier_error(exc)
            logger.warning(
                "trustmem verifier failed or timed out; falling back to deterministic: %s",
                fallback_reason,
            )
            # A failed/unavailable scorer cannot prove any dimension. Keep the
            # transition out of the commit path and preserve a dimension-shaped
            # audit record; retry is safer than silently approving a transition
            # on an unavailable verifier.
            return VerifierResult(
                "retry",
                [
                    "trustmem verifier failed; transition requires retry",
                ],
                model=self._model,
                prompt_version=self._prompt_version,
                mode="trustmem",
                dimensions=self._failed_dimensions(
                    f"verifier unavailable: {fallback_reason}"
                ),
                fallback_reason=fallback_reason,
            )

        failed = [name for name, score in dimensions.items() if not score.passed]
        decision = "approve" if not failed else "reject"
        reasons = [
            *(transition.reasons or []),
            *[
                f"{name} below threshold: {dimensions[name].reason}"
                for name in failed
            ],
        ]
        if not reasons and decision == "approve":
            reasons = ["coverage, preservation, and faithfulness passed"]
        log_extra = {
            "decision": decision,
            "failed_dimensions": failed,
            "coverage": dimensions["coverage"].score,
            "preservation": dimensions["preservation"].score,
            "faithfulness": dimensions["faithfulness"].score,
        }
        if failed:
            logger.warning("trustmem verifier rejected transition", extra=log_extra)
        else:
            logger.info("trustmem verifier approved transition", extra=log_extra)
        return VerifierResult(
            decision,
            reasons,
            model=self._model,
            prompt_version=self._prompt_version,
            mode="trustmem",
            dimensions=dimensions,
        )

    def _failed_dimensions(self, reason: str) -> dict[str, VerifierDimensionScore]:
        return {
            "coverage": VerifierDimensionScore(0.0, reason, self._coverage_threshold),
            "preservation": VerifierDimensionScore(
                0.0, reason, self._preservation_threshold
            ),
            "faithfulness": VerifierDimensionScore(
                0.0, reason, self._faithfulness_threshold
            ),
        }

    def _passing_dimensions(self, reason: str) -> dict[str, VerifierDimensionScore]:
        return {
            "coverage": VerifierDimensionScore(1.0, reason, self._coverage_threshold),
            "preservation": VerifierDimensionScore(
                1.0, reason, self._preservation_threshold
            ),
            "faithfulness": VerifierDimensionScore(
                1.0, reason, self._faithfulness_threshold
            ),
        }

    def _normalize_dimensions(
        self,
        raw: dict[str, Any],
    ) -> dict[str, VerifierDimensionScore]:
        thresholds = {
            "coverage": self._coverage_threshold,
            "preservation": self._preservation_threshold,
            "faithfulness": self._faithfulness_threshold,
        }
        result: dict[str, VerifierDimensionScore] = {}
        for name, threshold in thresholds.items():
            payload = raw.get(name)
            if payload is None:
                raise ValueError(f"missing verifier dimension: {name}")
            if isinstance(payload, VerifierDimensionScore):
                result[name] = payload
            elif isinstance(payload, dict):
                result[name] = VerifierDimensionScore(
                    score=float(payload["score"]),
                    reason=str(payload.get("reason") or ""),
                    threshold=threshold,
                )
            else:
                raise ValueError(f"unsupported verifier dimension payload: {name}")
        return result

    async def _llm_scores(
        self,
        transition: MemoryTransition,
        context: MemoryVerifierContext | None,
    ) -> dict[str, dict[str, Any]]:
        context = context or MemoryVerifierContext()
        llm = ChatGoogleGenerativeAI(
            model=self._model,
            temperature=0,
        ).with_structured_output(TrustMemLlmScores)
        payload = {
            "action": str(transition.action),
            "reasons": list(transition.reasons),
            "existing_memory_id": transition.existing_memory_id,
            "candidate": _compact_memory(transition.candidate),
            "sibling_candidates": [
                _compact_memory(memory) for memory in context.sibling_candidates[:20]
            ],
            "chunk": _compact_chunk(context.chunk),
            "M_old": [_compact_memory(memory) for memory in context.old_memories[:20]],
            "M_new": [_compact_memory(memory) for memory in context.new_memories[:20]],
        }
        scored = await llm.ainvoke(
            [
                SystemMessage(content=TRUSTMEM_SYSTEM_PROMPT),
                HumanMessage(
                    content=json.dumps(payload, ensure_ascii=False, default=str)
                ),
            ]
        )
        if isinstance(scored, dict):
            scored = TrustMemLlmScores.model_validate(scored)
        if not isinstance(scored, TrustMemLlmScores):
            raise ValueError(f"trustmem llm returned unexpected type: {type(scored)}")
        return scored.to_dimension_dict()

    def _heuristic_scores(
        self,
        transition: MemoryTransition,
        context: MemoryVerifierContext | None,
    ) -> dict[str, dict[str, Any]]:
        context = context or MemoryVerifierContext()
        chunk_text = _chunk_text(context.chunk)
        candidate_text = _candidate_text(transition)
        collective_text = _collective_candidate_text(
            candidate_text, context.sibling_candidates
        )
        old_text = "\n".join(m.memory_text for m in context.old_memories)

        coverage_score, coverage_reason = _score_coverage(chunk_text, collective_text)
        preservation_score, preservation_reason = _score_preservation(
            transition, old_text, candidate_text
        )
        faithfulness_score, faithfulness_reason = _score_faithfulness(
            chunk_text, candidate_text, transition
        )
        return {
            "coverage": {"score": coverage_score, "reason": coverage_reason},
            "preservation": {
                "score": preservation_score,
                "reason": preservation_reason,
            },
            "faithfulness": {
                "score": faithfulness_score,
                "reason": faithfulness_reason,
            },
        }


class TrustMemDryRunMemoryVerifier:
    def __init__(
        self,
        *,
        deterministic: DeterministicMemoryVerifier,
        trustmem: TrustMemInspiredMemoryVerifier,
    ) -> None:
        self._deterministic = deterministic
        self._trustmem = trustmem

    async def evaluate(
        self,
        transition: MemoryTransition,
        context: MemoryVerifierContext | None = None,
    ) -> VerifierResult:
        baseline = await self._deterministic.evaluate(transition, context)
        scored = await self._trustmem.evaluate(transition, context)
        return VerifierResult(
            baseline.decision,
            [*baseline.reasons, "trustmem dry-run score did not gate commit"],
            model=scored.model,
            prompt_version=scored.prompt_version,
            mode="trustmem-dry-run",
            dimensions=scored.dimensions,
            fallback_reason=scored.fallback_reason,
        )


def build_memory_verifier(settings: Settings) -> MemoryVerifier:
    deterministic = DeterministicMemoryVerifier()
    if settings.long_term_memory_verifier == "deterministic":
        return deterministic
    trustmem = TrustMemInspiredMemoryVerifier(
        model=settings.long_term_memory_trustmem_model,
        prompt_version=settings.long_term_memory_trustmem_prompt_version,
        coverage_threshold=settings.long_term_memory_trustmem_coverage_threshold,
        preservation_threshold=settings.long_term_memory_trustmem_preservation_threshold,
        faithfulness_threshold=settings.long_term_memory_trustmem_faithfulness_threshold,
        timeout_seconds=settings.long_term_memory_trustmem_timeout_seconds,
        fallback=deterministic,
    )
    if settings.long_term_memory_verifier == "trustmem":
        return trustmem
    return TrustMemDryRunMemoryVerifier(deterministic=deterministic, trustmem=trustmem)


def project_memory_state(
    transition: MemoryTransition,
    existing: Sequence[TravelMemory],
) -> list[TravelMemory]:
    if transition.action == TransitionAction.REJECT:
        return list(existing)
    if transition.action == TransitionAction.NOOP:
        return list(existing)
    if transition.action == TransitionAction.INSERT and transition.candidate:
        return [*existing, transition.candidate]
    if transition.action == TransitionAction.SUPERSEDE and transition.candidate:
        projected: list[TravelMemory] = []
        for memory in existing:
            if memory.memory_id == transition.existing_memory_id:
                projected.append(replace(memory, status=MemoryStatus.SUPERSEDED))
            else:
                projected.append(memory)
        projected.append(transition.candidate)
        return projected
    return list(existing)


def _uses_heuristic_model(model: str) -> bool:
    return str(model or "").strip().lower().startswith("heuristic")


def _format_verifier_error(exc: BaseException) -> str:
    message = str(exc).strip() or repr(exc)
    return f"{type(exc).__name__}: {message}"


def _compact_memory(memory: TravelMemory | None) -> dict[str, Any] | None:
    if memory is None:
        return None
    return {
        "memory_id": memory.memory_id,
        "memory_text": memory.memory_text,
        "status": str(memory.status),
        "category": str(memory.category),
        "condition": memory.condition,
        "evidence_text": (memory.evidence_text or "")[:500],
    }


def _compact_chunk(chunk: Sequence[dict[str, Any]]) -> list[dict[str, str]]:
    compact: list[dict[str, str]] = []
    for message in list(chunk)[-12:]:
        compact.append(
            {
                "type": str(message.get("type") or message.get("role") or ""),
                "content": str(message.get("content") or "")[:1000],
            }
        )
    return compact


async def _maybe_await(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value


def _chunk_text(chunk: Sequence[dict[str, Any]]) -> str:
    return "\n".join(str(message.get("content") or "") for message in chunk).lower()


def _candidate_text(transition: MemoryTransition) -> str:
    if not transition.candidate:
        return ""
    parts = [transition.candidate.memory_text]
    if transition.candidate.condition:
        parts.append(transition.candidate.condition)
    return "\n".join(parts).lower()


def _memory_text(memory: TravelMemory) -> str:
    parts = [memory.memory_text]
    if memory.condition:
        parts.append(memory.condition)
    return "\n".join(parts).lower()


def _collective_candidate_text(
    candidate_text: str,
    siblings: Sequence[TravelMemory],
) -> str:
    parts = [candidate_text]
    for sibling in siblings:
        parts.append(_memory_text(sibling))
    return "\n".join(part for part in parts if part.strip())


def _score_coverage(chunk_text: str, candidate_text: str) -> tuple[float, str]:
    required_groups = [
        {"business", "công tác", "work"},
        {"economy", "phổ thông", "du lịch", "leisure"},
        {"family", "gia đình", "trẻ nhỏ"},
    ]
    missing: list[str] = []
    for group in required_groups:
        if any(token in chunk_text for token in group) and not any(
            token in candidate_text for token in group
        ):
            missing.append("/".join(sorted(group)))
    if missing:
        return 0.55, "candidate omits durable condition(s): " + "; ".join(missing)
    if not candidate_text.strip():
        return 0.0, "no candidate memory to cover chunk"
    return 0.95, "candidate covers durable travel memory evidence"


def _score_preservation(
    transition: MemoryTransition,
    old_text: str,
    candidate_text: str,
) -> tuple[float, str]:
    if transition.action != TransitionAction.SUPERSEDE:
        return 0.95, "transition does not alter existing active memories"
    condition_tokens = ["economy", "phổ thông", "leisure", "du lịch", "công tác"]
    old_has_condition = any(token in old_text.lower() for token in condition_tokens)
    candidate_drops_condition = not any(token in candidate_text for token in condition_tokens)
    over_generalizes = any(token in candidate_text for token in ["always", "luôn"])
    if old_has_condition and (candidate_drops_condition or over_generalizes):
        return 0.45, "candidate over-generalizes or drops condition from M_old"
    return 0.95, "valid existing memory is preserved or safely superseded"


def _score_faithfulness(
    chunk_text: str,
    candidate_text: str,
    transition: MemoryTransition,
) -> tuple[float, str]:
    tool_markers = ["search_id", "total_results", "displayed_item_ids", "item_id"]
    station_tokens = ["ga", "station", "train"]
    user_confirmation = [
        "tôi thích",
        "tôi muốn",
        "tôi ưu tiên",
        "ưu tiên của tôi",
        "i prefer",
        "i want",
        "chọn",
    ]
    evidence = transition.candidate.evidence_text.lower() if transition.candidate else ""
    if any(marker in evidence for marker in tool_markers):
        return 0.1, "candidate evidence is tool/API output, not user evidence"
    if (
        any(marker in chunk_text for marker in tool_markers)
        and any(token in candidate_text for token in station_tokens)
        and not any(token in chunk_text for token in user_confirmation)
    ):
        return 0.2, "tool result was converted into user preference without confirmation"
    if not evidence.strip() and transition.candidate is not None:
        return 0.0, "candidate lacks evidence text"
    return 0.98, "candidate is supported by user evidence or valid prior memory"
