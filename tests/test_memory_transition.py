from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memory.consolidation import TransitionAction
from memory.long_term import MemoryCategory, MemoryDomain, TravelMemory
from memory.transition import (
    RelationComparison,
    ScopeJudgment,
    apply_relation_policy,
    build_policy_mock_judges_from_gold,
    find_exact_duplicate,
    merge_relation_input,
    partition_scope_batch,
    propose_transition,
)
from memory_eval.store import InMemoryLongTermMemoryRepository


def _mem(text: str, memory_id: str, *, condition: str | None = None) -> TravelMemory:
    return TravelMemory(
        memory_id=memory_id,
        user_id="user-1",
        memory_text=text,
        category=MemoryCategory.HOTEL_PREFERENCE,
        domain=MemoryDomain.HOTEL,
        evidence_text=text,
        source_thread_id="t1",
        condition=condition,
    )


def test_find_exact_duplicate_requires_condition_match():
    candidate = _mem("thích gần biển", "c1", condition="công tác")
    same = _mem("thích gần biển", "e1", condition="công tác")
    other = _mem("thích gần biển", "e2", condition="gia đình")
    assert find_exact_duplicate(candidate, [same], require_condition_match=True)
    assert (
        find_exact_duplicate(candidate, [other], require_condition_match=True) is None
    )


def test_partition_scope_batch_invariants():
    memories = [
        _mem("alpha hotel", "m1"),
        _mem("bravo hotel", "m2"),
        _mem("charlie hotel", "m3"),
        _mem("delta hotel", "m4"),
    ]
    judgments = [
        ScopeJudgment("m1", "different", 0.95),
        ScopeJudgment("m2", "same", 0.95),
        ScopeJudgment("m3", "same", 0.4),
        ScopeJudgment("m4", "uncertain", 0.9),
    ]
    part = partition_scope_batch(memories, judgments, confidence_threshold=0.85)
    assert part.dropped_ids == ("m1",)
    assert [m.memory_id for m in part.same_high_conf] == ["m2"]
    assert {m.memory_id for m in part.relation_direct} == {"m3", "m4"}


def test_merge_relation_input_exact_post_and_survivors():
    candidate = _mem("thích gần biển", "c1")
    same = [_mem("thích gần biển", "e1")]
    hit, survivors = merge_relation_input(
        same_high_conf=same,
        candidate=candidate,
        relation_direct=[_mem("khác", "e2")],
    )
    assert hit is not None and hit.memory_id == "e1"
    assert survivors == ()

    same2 = [_mem("ưu tiên boutique", "e1")]
    hit2, survivors2 = merge_relation_input(
        same_high_conf=same2,
        candidate=candidate,
        relation_direct=[_mem("uncertain", "e2")],
    )
    assert hit2 is None
    assert [m.memory_id for m in survivors2] == ["e1", "e2"]


def test_apply_relation_policy_equivalent_beats_supersedes():
    candidate = _mem("ưu tiên business", "c1")
    result = apply_relation_policy(
        candidate,
        [
            RelationComparison("m1", "equivalent", 0.94),
            RelationComparison("m2", "supersedes", 0.96),
        ],
        ranked_ids=["m2", "m1"],
        confidence_threshold=0.85,
    )
    assert result.early_exit is not None
    assert result.early_exit.action == TransitionAction.NOOP
    assert result.early_exit.existing_memory_id == "m1"
    assert any("existing_conflict_detected" in r for r in result.early_exit.reasons)


def test_apply_relation_policy_ambiguous_supersedes_continues():
    candidate = _mem("ưu tiên business", "c1")
    result = apply_relation_policy(
        candidate,
        [
            RelationComparison("m1", "supersedes", 0.94),
            RelationComparison("m2", "supersedes", 0.96),
        ],
        ranked_ids=["m1", "m2"],
    )
    assert result.early_exit is None
    assert result.audit_notes and result.audit_notes[0].startswith("ambiguous_target")


def test_propose_transition_policy_mock_supersede_and_insert():
    existing = [_mem("thích economy", "old-1")]
    candidate = _mem("thích business", "c1")
    repo = InMemoryLongTermMemoryRepository(existing)
    scope, relation = build_policy_mock_judges_from_gold(
        gold_action="supersede", existing=existing
    )
    transition = asyncio.run(
        propose_transition(
            candidate,
            repository=repo,
            scope_judge=scope,
            relation_judge=relation,
        )
    )
    assert transition.action == TransitionAction.SUPERSEDE
    assert transition.existing_memory_id == "old-1"

    empty_repo = InMemoryLongTermMemoryRepository([])
    insert = asyncio.run(
        propose_transition(
            candidate,
            repository=empty_repo,
            scope_judge=scope,
            relation_judge=relation,
        )
    )
    assert insert.action == TransitionAction.INSERT
