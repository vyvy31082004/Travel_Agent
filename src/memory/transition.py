from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal, Protocol, Sequence

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field

from memory.consolidation import (
    MemoryTransition,
    TransitionAction,
    calculate_transition,
    validate_memory_candidate,
)
from memory.embeddings import MemoryEmbeddingService
from memory.long_term import TravelMemory
from repositories.long_term_memory import LongTermMemoryRepository
from settings import Settings

__all__ = [
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_CONFIDENCE_THRESHOLD",
    "LlmRelationJudge",
    "LlmScopeJudge",
    "MockRelationJudge",
    "MockScopeJudge",
    "RelationComparison",
    "RelationJudgment",
    "RelationPolicyResult",
    "ScopeJudgment",
    "ScopePartition",
    "TransitionPath",
    "apply_relation_policy",
    "build_policy_mock_judges_from_gold",
    "build_transition_judges",
    "calculate_transition",
    "conditions_match",
    "find_exact_duplicate",
    "merge_relation_input",
    "normalize_condition",
    "normalize_statement",
    "partition_scope_batch",
    "propose_transition",
]

logger = logging.getLogger(__name__)

DEFAULT_CONFIDENCE_THRESHOLD = 0.85
DEFAULT_BATCH_SIZE = 10

ScopeRelation = Literal["same", "different", "uncertain"]
SemanticRelation = Literal["equivalent", "supersedes", "distinct", "uncertain"]


class TransitionPath(StrEnum):
    LEXICAL = "lexical"
    LLM = "llm"
    POLICY_MOCK = "policy-mock"


@dataclass(frozen=True)
class ScopeJudgment:
    existing_memory_id: str
    scope_relation: ScopeRelation
    confidence: float


@dataclass(frozen=True)
class RelationComparison:
    existing_memory_id: str
    relation: SemanticRelation
    confidence: float
    scope: str | None = None


@dataclass(frozen=True)
class RelationJudgment:
    comparisons: tuple[RelationComparison, ...] = ()
    selected_action: str | None = None
    selected_existing_memory_id: str | None = None


@dataclass(frozen=True)
class ScopePartition:
    """Per-batch partition after scope judge (before exact_post merge)."""

    same_high_conf: tuple[TravelMemory, ...] = ()
    relation_direct: tuple[TravelMemory, ...] = ()
    dropped_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class RelationPolicyResult:
    """Positive early-exit or continue scanning the pool."""

    early_exit: MemoryTransition | None = None
    audit_notes: tuple[str, ...] = ()


class ScopeJudge(Protocol):
    async def judge_scope(
        self, candidate: TravelMemory, existing: Sequence[TravelMemory]
    ) -> list[ScopeJudgment]:
        """Judge same/different/uncertain scope for each existing memory."""


class RelationJudge(Protocol):
    async def judge_relation(
        self, candidate: TravelMemory, existing: Sequence[TravelMemory]
    ) -> RelationJudgment:
        """Judge semantic relation for remaining comparison candidates."""


def normalize_statement(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[,.;!?]", " ", text)
    text = re.sub(r"\b(và|and)\b", " ", text)
    return " ".join(text.split())


def normalize_condition(condition: str | None) -> str | None:
    if condition is None:
        return None
    normalized = normalize_statement(condition)
    return normalized or None


def conditions_match(left: TravelMemory, right: TravelMemory) -> bool:
    return normalize_condition(left.condition) == normalize_condition(right.condition)


def find_exact_duplicate(
    candidate: TravelMemory,
    existing: Sequence[TravelMemory],
    *,
    require_condition_match: bool = True,
) -> TravelMemory | None:
    """Fast-path exact duplicate after normalize. Optionally require equal conditions."""
    normalized_candidate = normalize_statement(candidate.memory_text)
    if not normalized_candidate:
        return None
    for memory in existing:
        if require_condition_match and not conditions_match(candidate, memory):
            continue
        if normalize_statement(memory.memory_text) == normalized_candidate:
            return memory
    return None


def partition_scope_batch(
    batch: Sequence[TravelMemory],
    judgments: Sequence[ScopeJudgment],
    *,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> ScopePartition:
    """Partition one scope-judge batch. Not a global XOR branch."""
    by_id = {str(item.memory_id): item for item in batch if item.memory_id}
    seen: set[str] = set()
    same_high: list[TravelMemory] = []
    relation_direct: list[TravelMemory] = []
    dropped: list[str] = []

    for judgment in judgments:
        memory_id = str(judgment.existing_memory_id)
        memory = by_id.get(memory_id)
        if memory is None or memory_id in seen:
            continue
        seen.add(memory_id)
        high = judgment.confidence >= confidence_threshold
        if judgment.scope_relation == "different" and high:
            dropped.append(memory_id)
        elif judgment.scope_relation == "same" and high:
            same_high.append(memory)
        else:
            # uncertain, or same/different with low confidence
            relation_direct.append(memory)

    # Missing judgments → treat as uncertain (relation input)
    for memory_id, memory in by_id.items():
        if memory_id not in seen:
            relation_direct.append(memory)

    return ScopePartition(
        same_high_conf=tuple(same_high),
        relation_direct=tuple(relation_direct),
        dropped_ids=tuple(dropped),
    )


def merge_relation_input(
    *,
    same_high_conf: Sequence[TravelMemory],
    candidate: TravelMemory,
    relation_direct: Sequence[TravelMemory],
) -> tuple[TravelMemory | None, tuple[TravelMemory, ...]]:
    """
    Run exact_post on same-scope high-conf items.
    Returns (noop_hit, relation_input survivors).
    """
    exact = find_exact_duplicate(
        candidate, same_high_conf, require_condition_match=False
    )
    if exact is not None:
        return exact, ()
    survivors = list(same_high_conf)
    seen = {str(m.memory_id) for m in survivors if m.memory_id}
    for memory in relation_direct:
        mid = str(memory.memory_id) if memory.memory_id else None
        if mid and mid in seen:
            continue
        if mid:
            seen.add(mid)
        survivors.append(memory)
    return None, tuple(survivors)


def apply_relation_policy(
    candidate: TravelMemory,
    comparisons: Sequence[RelationComparison],
    *,
    ranked_ids: Sequence[str],
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    valid_ids: set[str] | None = None,
) -> RelationPolicyResult:
    """
    Map relation comparisons to NOOP / SUPERSEDE early-exit, or continue.
    Never early-exits INSERT; caller inserts only after the full pool is scanned.
    """
    allowed = valid_ids if valid_ids is not None else {
        str(item.existing_memory_id) for item in comparisons
    }
    rank_index = {memory_id: idx for idx, memory_id in enumerate(ranked_ids)}

    equivalents: list[RelationComparison] = []
    supersedes: list[RelationComparison] = []
    notes: list[str] = []

    for item in comparisons:
        memory_id = str(item.existing_memory_id)
        if memory_id not in allowed:
            continue
        if item.confidence < confidence_threshold:
            continue
        if item.relation == "equivalent":
            equivalents.append(item)
        elif item.relation == "supersedes":
            supersedes.append(item)

    if equivalents:
        equivalents_sorted = sorted(
            equivalents,
            key=lambda item: rank_index.get(str(item.existing_memory_id), 10**9),
        )
        chosen = equivalents_sorted[0]
        reasons = ["relation_equivalent"]
        if len(equivalents_sorted) > 1:
            extra = ",".join(
                str(item.existing_memory_id) for item in equivalents_sorted[1:]
            )
            reasons.append(f"additional_equivalent_ids:{extra}")
        if supersedes:
            conflict_ids = ",".join(str(item.existing_memory_id) for item in supersedes)
            reasons.append(f"existing_conflict_detected:{conflict_ids}")
            notes.append("existing_conflict_detected")
        return RelationPolicyResult(
            early_exit=MemoryTransition(
                action=TransitionAction.NOOP,
                candidate=candidate,
                existing_memory_id=str(chosen.existing_memory_id),
                reasons=reasons,
            ),
            audit_notes=tuple(notes),
        )

    if len(supersedes) == 1:
        chosen = supersedes[0]
        return RelationPolicyResult(
            early_exit=MemoryTransition(
                action=TransitionAction.SUPERSEDE,
                candidate=candidate,
                existing_memory_id=str(chosen.existing_memory_id),
                reasons=["relation_supersedes"],
            )
        )

    if len(supersedes) > 1:
        ids = ",".join(str(item.existing_memory_id) for item in supersedes)
        return RelationPolicyResult(
            audit_notes=(f"ambiguous_target:{ids}",),
        )

    return RelationPolicyResult()


async def propose_transition(
    candidate: TravelMemory,
    *,
    repository: LongTermMemoryRepository,
    scope_judge: ScopeJudge,
    relation_judge: RelationJudge,
    embedder: MemoryEmbeddingService | None = None,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> MemoryTransition:
    """Async production transition: SQL pool → exact → scope → relation."""
    rule_result = validate_memory_candidate(candidate)
    if not rule_result.ok:
        return MemoryTransition(
            action=TransitionAction.REJECT,
            candidate=candidate,
            reasons=rule_result.reasons,
        )

    user_id = candidate.user_id
    if not user_id:
        return MemoryTransition(
            action=TransitionAction.REJECT,
            candidate=candidate,
            reasons=["missing user_id"],
        )

    candidate_embedding: Sequence[float] | None = None
    embedding_model = ""
    embedding_dims = 0
    if embedder is not None:
        try:
            candidate_embedding = await embedder.embed_memory(candidate)
            embedding_model = embedder.model
            embedding_dims = embedder.dims
        except Exception as exc:
            logger.warning("transition embed failed; ranking without vectors: %s", exc)

    pool = await repository.fetch_transition_comparison_pool(
        user_id=user_id,
        category=str(candidate.category),
        domain=str(candidate.domain),
        candidate_embedding=candidate_embedding,
        embedding_model=embedding_model,
        embedding_dims=embedding_dims,
    )
    if not pool:
        return MemoryTransition(action=TransitionAction.INSERT, candidate=candidate)

    # exact_pre: condition-matched normalize duplicate across full pool
    pool_memories = [item.memory for item in pool]
    pre_dup = find_exact_duplicate(
        candidate, pool_memories, require_condition_match=True
    )
    if pre_dup is not None:
        return MemoryTransition(
            action=TransitionAction.NOOP,
            candidate=candidate,
            existing_memory_id=pre_dup.memory_id,
            reasons=["exact_duplicate"],
        )

    ranked_ids = [str(item.memory.memory_id) for item in pool if item.memory.memory_id]
    audit_notes: list[str] = []
    size = max(1, batch_size)

    for start in range(0, len(pool), size):
        batch_ranked = pool[start : start + size]
        batch = [item.memory for item in batch_ranked]
        scope_results = await scope_judge.judge_scope(candidate, batch)
        partition = partition_scope_batch(
            batch, scope_results, confidence_threshold=confidence_threshold
        )
        if partition.dropped_ids:
            audit_notes.append(
                f"scope_partition_dropped:{','.join(partition.dropped_ids)}"
            )

        exact_hit, relation_input = merge_relation_input(
            same_high_conf=partition.same_high_conf,
            candidate=candidate,
            relation_direct=partition.relation_direct,
        )
        if exact_hit is not None:
            return MemoryTransition(
                action=TransitionAction.NOOP,
                candidate=candidate,
                existing_memory_id=exact_hit.memory_id,
                reasons=["exact_duplicate", "same_scope"],
            )

        if not relation_input:
            continue

        relation = await relation_judge.judge_relation(candidate, relation_input)
        valid_ids = {str(m.memory_id) for m in relation_input if m.memory_id}
        decision = apply_relation_policy(
            candidate,
            relation.comparisons,
            ranked_ids=ranked_ids,
            confidence_threshold=confidence_threshold,
            valid_ids=valid_ids,
        )
        audit_notes.extend(decision.audit_notes)
        if decision.early_exit is not None:
            reasons = list(decision.early_exit.reasons)
            reasons.extend(audit_notes)
            return MemoryTransition(
                action=decision.early_exit.action,
                candidate=decision.early_exit.candidate,
                existing_memory_id=decision.early_exit.existing_memory_id,
                reasons=reasons,
            )

    reasons = ["relation_insert"]
    reasons.extend(audit_notes)
    return MemoryTransition(
        action=TransitionAction.INSERT,
        candidate=candidate,
        reasons=reasons,
    )


# --- Judges -----------------------------------------------------------------


class _ScopeItemModel(BaseModel):
    existing_memory_id: str
    scope_relation: Literal["same", "different", "uncertain"]
    confidence: float = Field(ge=0, le=1)


class _ScopeBatchModel(BaseModel):
    judgments: list[_ScopeItemModel] = Field(default_factory=list)


class _RelationItemModel(BaseModel):
    existing_memory_id: str
    scope: Literal["same", "different", "uncertain"] | None = None
    relation: Literal["equivalent", "supersedes", "distinct", "uncertain"]
    confidence: float = Field(ge=0, le=1)


class _RelationBatchModel(BaseModel):
    comparisons: list[_RelationItemModel] = Field(default_factory=list)
    selected_action: Literal["noop", "supersede", "insert"] | None = None
    selected_existing_memory_id: str | None = None


_SCOPE_SYSTEM = """You judge whether a candidate travel memory shares the same preference scope
as each existing active memory.

same: same user preference topic under the same condition/context
  (e.g. both about cabin class when traveling for business).
different: different condition or topic so they must not supersede each other
  (e.g. business-trip cabin vs family-trip cabin).
uncertain: not enough signal to decide.

Return one judgment per existing_memory_id with confidence in [0, 1]."""

_RELATION_SYSTEM = """You judge the semantic relation between a candidate travel memory
and each remaining existing active memory (same or uncertain scope).

equivalent: paraphrase / same durable preference → do not insert again.
supersedes: candidate replaces the existing preference (conflict or updated value)
  under the same scope (e.g. economy → business for the same condition).
distinct: independent preference; keep both.
uncertain: cannot decide.

Return comparisons for every existing_memory_id. selected_action is optional hint only."""


def _memory_payload(memory: TravelMemory) -> dict[str, Any]:
    return {
        "memory_id": memory.memory_id,
        "memory_text": memory.memory_text,
        "category": str(memory.category),
        "domain": str(memory.domain),
        "condition": memory.condition,
        "evidence_text": memory.evidence_text,
    }


class LlmScopeJudge:
    def __init__(self, *, model: str) -> None:
        self._model = model

    async def judge_scope(
        self, candidate: TravelMemory, existing: Sequence[TravelMemory]
    ) -> list[ScopeJudgment]:
        if not existing:
            return []
        llm = ChatGoogleGenerativeAI(model=self._model, temperature=0).with_structured_output(
            _ScopeBatchModel
        )
        payload = {
            "candidate": _memory_payload(candidate),
            "existing": [_memory_payload(item) for item in existing],
        }
        result = await llm.ainvoke(
            [
                SystemMessage(content=_SCOPE_SYSTEM),
                HumanMessage(content=str(payload)),
            ]
        )
        if not isinstance(result, _ScopeBatchModel):
            result = _ScopeBatchModel.model_validate(result)
        return [
            ScopeJudgment(
                existing_memory_id=item.existing_memory_id,
                scope_relation=item.scope_relation,
                confidence=item.confidence,
            )
            for item in result.judgments
        ]


class LlmRelationJudge:
    def __init__(self, *, model: str) -> None:
        self._model = model

    async def judge_relation(
        self, candidate: TravelMemory, existing: Sequence[TravelMemory]
    ) -> RelationJudgment:
        if not existing:
            return RelationJudgment()
        llm = ChatGoogleGenerativeAI(model=self._model, temperature=0).with_structured_output(
            _RelationBatchModel
        )
        payload = {
            "candidate": _memory_payload(candidate),
            "existing": [_memory_payload(item) for item in existing],
        }
        result = await llm.ainvoke(
            [
                SystemMessage(content=_RELATION_SYSTEM),
                HumanMessage(content=str(payload)),
            ]
        )
        if not isinstance(result, _RelationBatchModel):
            result = _RelationBatchModel.model_validate(result)
        return RelationJudgment(
            comparisons=tuple(
                RelationComparison(
                    existing_memory_id=item.existing_memory_id,
                    relation=item.relation,
                    confidence=item.confidence,
                    scope=item.scope,
                )
                for item in result.comparisons
            ),
            selected_action=result.selected_action,
            selected_existing_memory_id=result.selected_existing_memory_id,
        )


@dataclass
class MockScopeJudge:
    """Fixed or callable scope judgments for offline eval."""

    judgments: list[ScopeJudgment] = field(default_factory=list)
    by_id: dict[str, ScopeJudgment] = field(default_factory=dict)

    async def judge_scope(
        self, candidate: TravelMemory, existing: Sequence[TravelMemory]
    ) -> list[ScopeJudgment]:
        out: list[ScopeJudgment] = []
        for memory in existing:
            mid = str(memory.memory_id or "")
            if mid and mid in self.by_id:
                out.append(self.by_id[mid])
            else:
                match = next(
                    (
                        item
                        for item in self.judgments
                        if item.existing_memory_id == mid
                    ),
                    None,
                )
                if match is not None:
                    out.append(match)
                else:
                    out.append(
                        ScopeJudgment(
                            existing_memory_id=mid,
                            scope_relation="same",
                            confidence=1.0,
                        )
                    )
        return out


@dataclass
class MockRelationJudge:
    """Fixed relation judgments for offline eval."""

    judgment: RelationJudgment = field(default_factory=RelationJudgment)
    by_existing_id: dict[str, RelationComparison] = field(default_factory=dict)

    async def judge_relation(
        self, candidate: TravelMemory, existing: Sequence[TravelMemory]
    ) -> RelationJudgment:
        if self.by_existing_id:
            comparisons = []
            for memory in existing:
                mid = str(memory.memory_id or "")
                if mid in self.by_existing_id:
                    comparisons.append(self.by_existing_id[mid])
                else:
                    comparisons.append(
                        RelationComparison(
                            existing_memory_id=mid,
                            relation="distinct",
                            confidence=1.0,
                        )
                    )
            return RelationJudgment(comparisons=tuple(comparisons))
        if self.judgment.comparisons:
            allowed = {str(m.memory_id) for m in existing if m.memory_id}
            filtered = tuple(
                item
                for item in self.judgment.comparisons
                if str(item.existing_memory_id) in allowed
            )
            return RelationJudgment(
                comparisons=filtered,
                selected_action=self.judgment.selected_action,
                selected_existing_memory_id=self.judgment.selected_existing_memory_id,
            )
        return RelationJudgment(
            comparisons=tuple(
                RelationComparison(
                    existing_memory_id=str(memory.memory_id or ""),
                    relation="distinct",
                    confidence=1.0,
                )
                for memory in existing
            )
        )


def build_policy_mock_judges_from_gold(
    *,
    gold_action: str,
    existing: Sequence[TravelMemory],
    confidence: float = 1.0,
) -> tuple[MockScopeJudge, MockRelationJudge]:
    """Derive mock judges so policy-mock eval exercises mapping without an LLM."""
    gold = gold_action.lower().strip()
    scope_by_id: dict[str, ScopeJudgment] = {}
    relation_by_id: dict[str, RelationComparison] = {}
    for memory in existing:
        mid = str(memory.memory_id or "")
        if not mid:
            continue
        scope_by_id[mid] = ScopeJudgment(
            existing_memory_id=mid,
            scope_relation="same",
            confidence=confidence,
        )
        if gold == "noop":
            relation_by_id[mid] = RelationComparison(
                existing_memory_id=mid,
                relation="equivalent",
                confidence=confidence,
            )
        elif gold == "supersede":
            relation_by_id[mid] = RelationComparison(
                existing_memory_id=mid,
                relation="supersedes",
                confidence=confidence,
            )
        else:
            relation_by_id[mid] = RelationComparison(
                existing_memory_id=mid,
                relation="distinct",
                confidence=confidence,
            )
    # For supersede with multiple existings, keep only the first as supersedes
    if gold == "supersede" and len(relation_by_id) > 1:
        first = True
        for mid in list(relation_by_id):
            if first:
                first = False
                continue
            relation_by_id[mid] = RelationComparison(
                existing_memory_id=mid,
                relation="distinct",
                confidence=confidence,
            )
    return MockScopeJudge(by_id=scope_by_id), MockRelationJudge(
        by_existing_id=relation_by_id
    )


def build_transition_judges(
    settings: Settings,
) -> tuple[ScopeJudge, RelationJudge]:
    model = settings.long_term_memory_transition_model
    return LlmScopeJudge(model=model), LlmRelationJudge(model=model)
