from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from memory.commit import MemoryCommitAdapter
from memory.consolidation import calculate_transition
from memory.long_term import MemoryFamily, MemoryStatus
from memory.verifier import DeterministicMemoryVerifier
from memory_eval.candidate_extraction import MetricValue
from memory_eval.common import load_jsonl, memory_from_dict
from memory_eval.store import InMemoryLongTermMemoryRepository
from services.long_term_memory import MemoryService
from settings import Settings


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


def evaluate_transition_file(path: str | Path) -> SuiteReport:
    rows = load_jsonl(path)
    correct = 0
    conflict_total = 0
    conflict_correct = 0
    case_rows: list[dict[str, Any]] = []
    for raw in rows:
        existing = [memory_from_dict(item) for item in raw.get("existing") or []]
        candidate = memory_from_dict(raw["candidate"])
        predicted = calculate_transition(candidate, existing)
        gold = str(raw["gold_action"]).lower()
        ok = str(predicted.action) == gold
        correct += int(ok)
        case_rows.append(
            {
                "case_id": raw["case_id"],
                "gold_action": gold,
                "predicted_action": str(predicted.action),
                "correct": ok,
            }
        )
        if gold == "supersede":
            conflict_total += 1
    return SuiteReport(
        suite="transition",
        metrics={"transition_accuracy": _ratio(correct, len(rows))},
        cases=tuple(case_rows),
    )


async def evaluate_supersession_file(path: str | Path, settings: Settings) -> SuiteReport:
    rows = load_jsonl(path)
    conflict_rows = [row for row in rows if str(row.get("gold_action")).lower() == "supersede"]
    correct = 0
    case_rows: list[dict[str, Any]] = []
    for raw in conflict_rows:
        existing = [memory_from_dict(item) for item in raw.get("existing") or []]
        candidate = memory_from_dict(raw["candidate"])
        transition = calculate_transition(candidate, existing)
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
            }
        )
    return SuiteReport(
        suite="supersession",
        metrics={"supersession_correctness": _ratio(correct, len(conflict_rows))},
        cases=tuple(case_rows),
    )


async def evaluate_retrieval_file(path: str | Path, settings: Settings) -> SuiteReport:
    rows = load_jsonl(path)
    k = settings.long_term_memory_recall_limit
    relevant_hit = 0
    relevant_total = 0
    precision_hit = 0
    precision_slots = 0
    wrong_user = 0
    recalled_total = 0
    inactive_hit = 0
    case_rows: list[dict[str, Any]] = []
    for raw in rows:
        memories = [memory_from_dict(item) for item in raw.get("memories") or []]
        relevant_ids = {
            str(item["memory_id"])
            for item in raw.get("memories") or []
            if item.get("relevant") and item.get("memory_id")
        }
        repo = InMemoryLongTermMemoryRepository(memories)
        service = MemoryService(settings=settings, repository=repo)
        families = tuple(
            {
                MemoryFamily(memory.family)
                for memory in memories
                if memory.user_id == raw["user_id"]
            }
            or {MemoryFamily.TRAVEL_PREFERENCES}
        )
        result = await service.recall(
            user_id=raw["user_id"],
            query=raw["query"],
            families=families,
        )
        top = list(result.recalled_memory_ids)[:k]
        hits = sum(memory_id in relevant_ids for memory_id in top)
        relevant_hit += hits
        relevant_total += len(relevant_ids)
        precision_hit += hits
        precision_slots += k
        recalled_total += len(result.recalled_memory_ids)
        leaked_users = 0
        leaked_inactive = 0
        for memory_id in result.recalled_memory_ids:
            memory = repo.memories.get(memory_id)
            if memory is None:
                continue
            if memory.user_id != raw["user_id"]:
                leaked_users += 1
            if not memory.is_active or MemoryStatus(memory.status) != MemoryStatus.ACTIVE:
                leaked_inactive += 1
        wrong_user += leaked_users
        inactive_hit += leaked_inactive
        case_rows.append(
            {
                "case_id": raw["case_id"],
                "recalled_memory_ids": result.recalled_memory_ids,
                "relevant_in_top_k": hits,
                "wrong_user": leaked_users,
                "inactive": leaked_inactive,
            }
        )
    return SuiteReport(
        suite="retrieval",
        metrics={
            "recall_at_k": _ratio(relevant_hit, relevant_total),
            "precision_at_k": _ratio(precision_hit, precision_slots),
            "cross_user_leakage_rate": _ratio(wrong_user, recalled_total),
            "inactive_leakage_rate": _ratio(inactive_hit, recalled_total),
        },
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
        long_term_memory_vector_search_enabled=False,
    )
    values.update(overrides)
    return Settings(**values)
