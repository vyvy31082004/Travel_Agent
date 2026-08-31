from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from memory.commit import MemoryCommitAdapter
from memory.consolidation import calculate_transition
from memory.applicability import ApplicabilityJudge, ApplicabilityLabel, build_applicability_judge
from memory.long_term import MemoryFamily, MemoryStatus
from memory.task_router import build_action_inferrer
from memory.transition import (
    build_policy_mock_judges_from_gold,
    build_transition_judges,
    propose_transition,
)
from memory.verifier import DeterministicMemoryVerifier
from memory_eval.candidate_extraction import MetricValue
from memory_eval.common import load_jsonl, memory_from_dict
from memory_eval.store import InMemoryLongTermMemoryRepository
from services.long_term_memory import MemoryService
from settings import Settings

DEFAULT_FIXTURE_DIR = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "long_term_memory_eval"
)


def filter_rows_by_split(
    rows: list[dict[str, Any]], split: str = "all"
) -> list[dict[str, Any]]:
    if split == "all":
        return rows
    filtered = [row for row in rows if str(row.get("split") or "") == split]
    if not filtered:
        raise ValueError(f"no cases found for split={split!r}")
    return filtered


def _ratio(numerator: int, denominator: int) -> MetricValue:
    return MetricValue(
        numerator,
        denominator,
        None if denominator == 0 else numerator / denominator,
    )


@dataclass(frozen=True)
class SuiteReport:
    suite: str
    metrics: dict[str, MetricValue]
    cases: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "metrics": {name: metric.to_dict() for name, metric in self.metrics.items()},
            "cases": list(self.cases),
        }


async def evaluate_transition_file(
    path: str | Path,
    *,
    split: str = "all",
    transition_path: str = "lexical",
    settings: Settings | None = None,
) -> SuiteReport:
    rows = filter_rows_by_split(load_jsonl(path), split)
    correct = 0
    case_rows: list[dict[str, Any]] = []
    resolved_settings = settings or make_eval_settings(
        long_term_memory_transition_path=transition_path
    )
    scope_judge = relation_judge = None
    if transition_path == "llm":
        scope_judge, relation_judge = build_transition_judges(resolved_settings)

    for raw in rows:
        existing = [memory_from_dict(item) for item in raw.get("existing") or []]
        candidate = memory_from_dict(raw["candidate"])
        predicted = await _predict_transition(
            candidate,
            existing,
            transition_path=transition_path,
            gold_action=str(raw["gold_action"]),
            settings=resolved_settings,
            scope_judge=scope_judge,
            relation_judge=relation_judge,
            case_payload=raw,
        )
        gold = str(raw["gold_action"]).lower()
        ok = str(predicted.action) == gold
        correct += int(ok)
        case_rows.append(
            {
                "case_id": raw["case_id"],
                "gold_action": gold,
                "predicted_action": str(predicted.action),
                "correct": ok,
                "transition_path": transition_path,
            }
        )
    return SuiteReport(
        suite="transition",
        metrics={"transition_accuracy": _ratio(correct, len(rows))},
        cases=tuple(case_rows),
    )


async def _predict_transition(
    candidate,
    existing,
    *,
    transition_path: str,
    gold_action: str,
    settings: Settings,
    scope_judge=None,
    relation_judge=None,
    case_payload: dict[str, Any] | None = None,
):
    if transition_path == "lexical":
        return calculate_transition(candidate, existing)

    repo = InMemoryLongTermMemoryRepository(existing)
    if transition_path == "policy-mock":
        if case_payload and case_payload.get("scope_judgments") is not None:
            from memory.transition import MockRelationJudge, MockScopeJudge, RelationComparison, ScopeJudgment

            scope_judge = MockScopeJudge(
                by_id={
                    item["existing_memory_id"]: ScopeJudgment(
                        existing_memory_id=item["existing_memory_id"],
                        scope_relation=item["scope_relation"],
                        confidence=float(item["confidence"]),
                    )
                    for item in case_payload["scope_judgments"]
                }
            )
            relation_judge = MockRelationJudge(
                by_existing_id={
                    item["existing_memory_id"]: RelationComparison(
                        existing_memory_id=item["existing_memory_id"],
                        relation=item["relation"],
                        confidence=float(item["confidence"]),
                        scope=item.get("scope"),
                    )
                    for item in case_payload.get("relation_comparisons") or []
                }
            )
        else:
            scope_judge, relation_judge = build_policy_mock_judges_from_gold(
                gold_action=gold_action,
                existing=existing,
            )
    elif transition_path == "llm":
        if scope_judge is None or relation_judge is None:
            scope_judge, relation_judge = build_transition_judges(settings)
    else:
        raise ValueError(f"unsupported transition_path={transition_path!r}")

    return await propose_transition(
        candidate,
        repository=repo,
        scope_judge=scope_judge,
        relation_judge=relation_judge,
        embedder=None,
        confidence_threshold=settings.long_term_memory_transition_confidence_threshold,
        batch_size=settings.long_term_memory_transition_batch_size,
    )


async def evaluate_supersession_file(
    path: str | Path,
    settings: Settings,
    *,
    split: str = "all",
    transition_path: str = "lexical",
) -> SuiteReport:
    rows = filter_rows_by_split(load_jsonl(path), split)
    conflict_rows = [
        row for row in rows if str(row.get("gold_action")).lower() == "supersede"
    ]
    correct = 0
    case_rows: list[dict[str, Any]] = []
    scope_judge = relation_judge = None
    if transition_path == "llm":
        scope_judge, relation_judge = build_transition_judges(settings)

    for raw in conflict_rows:
        existing = [memory_from_dict(item) for item in raw.get("existing") or []]
        candidate = memory_from_dict(raw["candidate"])
        transition = await _predict_transition(
            candidate,
            existing,
            transition_path=transition_path,
            gold_action=str(raw["gold_action"]),
            settings=settings,
            scope_judge=scope_judge,
            relation_judge=relation_judge,
            case_payload=raw,
        )
        repo = InMemoryLongTermMemoryRepository(existing)
        adapter = MemoryCommitAdapter(
            repository=repo,
            verifier=DeterministicMemoryVerifier(),
        )
        await adapter.verify_and_commit(
            transition=transition,
            user_id=candidate.user_id or "user-1",
            thread_id=candidate.source_thread_id,
        )
        old_id = transition.existing_memory_id
        old = repo.memories.get(old_id or "")
        new_memories = [
            memory
            for memory_id, memory in repo.memories.items()
            if memory_id != old_id
        ]
        new = next((memory for memory in new_memories if memory.is_active), None)
        service = MemoryService(settings=settings, repository=repo)
        recalled = await service.recall(
            user_id=candidate.user_id,
            query=candidate.memory_text,
            families=(candidate.family,),
        )
        old_inactive = old is not None and not old.is_active
        linked = bool(new and new.supersedes_memory_id == old_id)
        old_not_recalled = old_id not in recalled.recalled_memory_ids
        ok = old_inactive and linked and old_not_recalled
        correct += int(ok)
        case_rows.append(
            {
                "case_id": raw["case_id"],
                "old_inactive": old_inactive,
                "linked": linked,
                "old_not_recalled": old_not_recalled,
                "correct": ok,
                "predicted_action": str(transition.action),
                "transition_path": transition_path,
            }
        )
    return SuiteReport(
        suite="supersession",
        metrics={"supersession_correctness": _ratio(correct, len(conflict_rows))},
        cases=tuple(case_rows),
    )


def build_retrieval_applicability_judge(
    mode: str,
    *,
    judge_model: str,
) -> ApplicabilityJudge:
    if mode == "llm":
        from langchain_google_genai import ChatGoogleGenerativeAI

        llm = ChatGoogleGenerativeAI(model=judge_model, temperature=0)
        return build_applicability_judge(llm=llm, use_llm=True)
    return build_applicability_judge(llm=None, use_llm=False)


async def evaluate_retrieval_file(
    path: str | Path,
    settings: Settings,
    *,
    split: str = "all",
    retrieval_path: str = "inmemory",
    applicability_judge: str = "rule",
    judge_model: str = "gemini-2.5-flash",
) -> SuiteReport:
    del retrieval_path  # domain recall is always in-memory SQL pool
    judge = build_retrieval_applicability_judge(
        applicability_judge,
        judge_model=judge_model,
    )
    from collections import Counter

    rows = filter_rows_by_split(load_jsonl(path), split)

    pool_complete_num = 0
    pool_complete_den = 0
    wrong_user_candidate = 0
    wrong_domain_candidate = 0
    inactive_candidate = 0
    candidate_total = 0

    apply_hit = 0
    apply_total = 0
    precision_hit = 0
    precision_den = 0
    uncertain_in_final = 0
    final_total = 0
    overridden_leak_num = 0
    overridden_leak_den = 0

    wrong_user_context = 0
    wrong_domain_context = 0
    inactive_context = 0

    confusion: Counter[tuple[str, str]] = Counter()
    case_rows: list[dict[str, Any]] = []

    inferrer = build_action_inferrer(
        llm=None,
        use_llm=settings.long_term_memory_action_inference_enabled,
    )

    def _normalize_label(value: str) -> str:
        return str(value or "").strip().lower()

    def _pool_leakage(
        ids: set[str],
        repo: InMemoryLongTermMemoryRepository,
        *,
        user_id: str,
        domain: str,
    ) -> tuple[int, int, int]:
        wrong_user = wrong_domain = inactive = 0
        for memory_id in ids:
            memory = repo.memories.get(memory_id)
            if memory is None:
                continue
            if memory.user_id != user_id:
                wrong_user += 1
            if str(memory.domain) != domain:
                wrong_domain += 1
            if not memory.is_active or MemoryStatus(memory.status) != MemoryStatus.ACTIVE:
                inactive += 1
        return wrong_user, wrong_domain, inactive

    def _macro_f1(counter: Counter[tuple[str, str]]) -> MetricValue:
        labels = [str(item) for item in ApplicabilityLabel]
        scores: list[float] = []
        for label in labels:
            tp = counter.get((label, label), 0)
            fp = sum(
                count
                for (gold, pred), count in counter.items()
                if pred == label and gold != label
            )
            fn = sum(
                count
                for (gold, pred), count in counter.items()
                if gold == label and pred != label
            )
            if tp == 0 and fp == 0 and fn == 0:
                continue
            precision = tp / (tp + fp) if (tp + fp) else 0.0
            recall = tp / (tp + fn) if (tp + fn) else 0.0
            if precision + recall == 0:
                scores.append(0.0)
            else:
                scores.append(2 * precision * recall / (precision + recall))
        if not scores:
            return _ratio(0, 0)
        mean = sum(scores) / len(scores)
        return MetricValue(int(mean * 1000), 1000, mean)

    for raw in rows:
        memories = [memory_from_dict(item) for item in raw.get("memory_store") or []]
        repo = InMemoryLongTermMemoryRepository(memories)
        service = MemoryService(
            settings=settings,
            repository=repo,
            applicability_judge=judge,
        )

        user_id = str(raw["user_id"])
        domain = str(raw["domain"])
        query = str(raw.get("user_query") or "")
        domain_state = dict(raw.get("domain_state") or {})
        expected_pool = {str(item) for item in raw.get("expected_sql_pool") or []}
        expected_applicability = {
            str(k): _normalize_label(v)
            for k, v in (raw.get("expected_applicability") or {}).items()
        }
        expected_action = raw.get("expected_action")

        inferred_action = await inferrer.infer_domain_action(
            user_query=query,
            domain=domain,
            domain_state=domain_state,
        )
        action_ok = expected_action is None or str(inferred_action) == str(expected_action)

        candidates = await service.fetch_domain_candidates(user_id=user_id, domain=domain)
        actual_pool = {
            str(memory.memory_id) for memory in candidates if memory.memory_id
        }
        sql_pool_ok = actual_pool == expected_pool

        pool_complete_num += len(expected_pool & actual_pool)
        pool_complete_den += len(expected_pool)
        candidate_total += len(actual_pool)
        wu, wd, ina = _pool_leakage(
            actual_pool, repo, user_id=user_id, domain=domain
        )
        wrong_user_candidate += wu
        wrong_domain_candidate += wd
        inactive_candidate += ina

        recall = await service.recall_domain_with_applicability(
            user_id=user_id,
            query=query,
            domain=domain,
            domain_action=str(expected_action) if expected_action else None,
            domain_state=domain_state,
        )
        final_ids = set(recall.recalled_memory_ids or [])
        gold_apply = {
            mid for mid, label in expected_applicability.items() if label == "apply"
        }
        gold_uncertain = {
            mid
            for mid, label in expected_applicability.items()
            if label == "uncertain"
        }
        gold_overridden = {
            mid
            for mid, label in expected_applicability.items()
            if label == "overridden"
        }

        apply_hit += len(gold_apply & final_ids)
        apply_total += len(gold_apply)
        precision_hit += len(gold_apply & final_ids)
        precision_den += len(final_ids)
        uncertain_in_final += len(gold_uncertain & final_ids)
        final_total += len(final_ids)
        overridden_leak_num += len(gold_overridden & final_ids)
        overridden_leak_den += len(gold_overridden)

        wu, wd, ina = _pool_leakage(final_ids, repo, user_id=user_id, domain=domain)
        wrong_user_context += wu
        wrong_domain_context += wd
        inactive_context += ina

        predicted_by_id = {
            str(item["memory_id"]): _normalize_label(item.get("label"))
            for item in recall.applicability or []
        }
        for memory_id, gold_label in expected_applicability.items():
            predicted = predicted_by_id.get(memory_id, "missing")
            confusion[(gold_label, predicted)] += 1

        expected_presented = raw.get("expected_presented_constraints") or []
        presented_ok = True
        for item in expected_presented:
            memory_id = str(item.get("memory_id") or "")
            if memory_id not in final_ids:
                presented_ok = False
                break
            if expected_applicability.get(memory_id) not in {"apply", "uncertain"}:
                presented_ok = False
                break

        case_rows.append(
            {
                "case_id": raw["case_id"],
                "scenario_type": raw.get("scenario_type"),
                "sql_pool_ok": sql_pool_ok,
                "action_ok": action_ok,
                "actual_pool": sorted(actual_pool),
                "expected_pool": sorted(expected_pool),
                "final_context_ids": sorted(final_ids),
                "judge_labels": predicted_by_id,
                "overridden_leaked": sorted(gold_overridden & final_ids),
                "presented_ok": presented_ok,
            }
        )

    metrics = {
        "candidate_pool_completeness": _ratio(pool_complete_num, pool_complete_den),
        "cross_user_candidate_leakage": _ratio(wrong_user_candidate, candidate_total),
        "cross_domain_candidate_leakage": _ratio(
            wrong_domain_candidate, candidate_total
        ),
        "inactive_candidate_leakage": _ratio(inactive_candidate, candidate_total),
        "context_recall": _ratio(apply_hit, apply_total),
        "context_precision": _ratio(precision_hit, precision_den),
        "uncertain_context_rate": _ratio(uncertain_in_final, final_total),
        "overridden_leakage_rate": _ratio(overridden_leak_num, overridden_leak_den),
        "applicability_macro_f1": _macro_f1(confusion),
        "cross_user_context_leakage": _ratio(wrong_user_context, final_total),
        "cross_domain_context_leakage": _ratio(wrong_domain_context, final_total),
        "inactive_context_leakage": _ratio(inactive_context, final_total),
    }
    return SuiteReport(
        suite="retrieval",
        metrics=metrics,
        cases=tuple(case_rows),
    )


_TOKEN_RE = re.compile(r"[^\w]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFC", text).casefold()
    return [token for token in _TOKEN_RE.split(normalized) if token]


def partial_f1(predicted: str, gold: str) -> MetricValue:
    pred_tokens = tokenize(predicted)
    gold_tokens = tokenize(gold)
    if not pred_tokens and not gold_tokens:
        return _ratio(0, 0)
    overlap = 0
    remaining = list(gold_tokens)
    for token in pred_tokens:
        if token in remaining:
            remaining.remove(token)
            overlap += 1
    precision = overlap / len(pred_tokens) if pred_tokens else 0.0
    recall = overlap / len(gold_tokens) if gold_tokens else 0.0
    if precision + recall == 0:
        return MetricValue(overlap, len(gold_tokens) or len(pred_tokens), 0.0)
    return MetricValue(
        overlap,
        len(gold_tokens) or len(pred_tokens),
        2 * precision * recall / (precision + recall),
    )


def evaluate_answer_file(path: str | Path) -> SuiteReport:
    rows = load_jsonl(path)
    correct = 0
    f1_sum = 0.0
    f1_count = 0
    case_rows: list[dict[str, Any]] = []
    for raw in rows:
        predicted = str(raw["predicted_answer"])
        gold = str(raw["gold_answer"])
        group = str(raw.get("group") or "single-hop")
        f1 = partial_f1(predicted, gold)
        ok = tokenize(predicted) == tokenize(gold)
        correct += int(ok)
        if f1.value is not None:
            f1_sum += f1.value
            f1_count += 1
        case_rows.append(
            {
                "case_id": raw["case_id"],
                "group": group,
                "correct": ok,
                "f1": f1.value,
            }
        )
    mean_f1 = None if f1_count == 0 else f1_sum / f1_count
    return SuiteReport(
        suite="answer",
        metrics={
            "answer_accuracy": _ratio(correct, len(rows)),
            "partial_f1": MetricValue(f1_count, len(rows), mean_f1),
        },
        cases=tuple(case_rows),
    )


def make_eval_settings(**overrides: Any) -> Settings:
    values = dict(
        database_url="postgresql://user:pass@localhost/db",
        cookie_secret="secret",
        long_term_memory_recall_enabled=True,
        long_term_memory_write_enabled=False,
        long_term_memory_recall_limit=5,
        long_term_memory_domain_candidate_limit=50,
        long_term_memory_action_inference_enabled=False,
        long_term_memory_applicability_judge_enabled=True,
        long_term_memory_vector_search_enabled=False,
        long_term_memory_transition_path="lexical",
        long_term_memory_transition_model="gemini-2.5-flash",
        long_term_memory_transition_confidence_threshold=0.85,
        long_term_memory_transition_batch_size=10,
    )
    values.update(overrides)
    return Settings(**values)
