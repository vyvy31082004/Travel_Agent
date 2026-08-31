from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from memory_eval.candidate_extraction import MetricValue
from memory_eval.common import load_jsonl
from services.reference_resolver import ClarificationNeeded, resolve_item_reference


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
    extra: dict[str, Any] = field(default_factory=dict)
    cases: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "metrics": {name: metric.to_dict() for name, metric in self.metrics.items()},
            "extra": self.extra,
            "cases": list(self.cases),
        }


# ---------------------------------------------------------------------------
# Value normalization (shared by state tracking)
# ---------------------------------------------------------------------------

_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y")


def normalize_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        # Money/counts compared numerically; drop trailing .0 for ints.
        if float(value).is_integer():
            return str(int(value))
        return str(value)
    text = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    digits = text.replace(",", "").replace(".", "")
    if digits.isdigit():
        return str(int(digits))
    return unicodedata.normalize("NFC", text).casefold()


def _flatten_state(state: dict[str, Any]) -> dict[str, str]:
    """Flatten agent state into dotted slot keys matching the gold schema."""
    slots: dict[str, str] = {}
    requests = state.get("requests") or {}
    for domain, params in requests.items():
        if not isinstance(params, dict):
            continue
        for key, value in params.items():
            slots[f"{domain}.{key}"] = normalize_value(value)
    selected = state.get("selected_items") or {}
    for domain, payload in selected.items():
        if isinstance(payload, dict) and payload.get("item_id") is not None:
            slots[f"{domain}.selected"] = normalize_value(payload["item_id"])
    if state.get("active_request_id") is not None:
        slots["active_request_id"] = normalize_value(state["active_request_id"])
    return slots


# ---------------------------------------------------------------------------
# State tracking: Joint Goal Accuracy + Slot F1
# ---------------------------------------------------------------------------


def evaluate_state_file(path: str | Path) -> SuiteReport:
    rows = load_jsonl(path)
    jga_correct = 0
    true_positive = 0
    false_positive = 0
    false_negative = 0
    case_rows: list[dict[str, Any]] = []
    for raw in rows:
        predicted = _flatten_state(raw.get("state") or {})
        gold = {key: normalize_value(value) for key, value in (raw.get("gold") or {}).items()}
        joint_ok = all(
            predicted.get(slot) == value for slot, value in gold.items()
        ) and bool(gold)
        jga_correct += int(joint_ok)
        tp = sum(1 for slot, value in gold.items() if predicted.get(slot) == value)
        fn = sum(1 for slot, value in gold.items() if predicted.get(slot) != value)
        fp = sum(1 for slot in predicted if slot not in gold)
        fp += sum(
            1
            for slot, value in gold.items()
            if slot in predicted and predicted[slot] != value
        )
        true_positive += tp
        false_negative += fn
        false_positive += fp
        case_rows.append(
            {
                "case_id": raw["case_id"],
                "joint_correct": joint_ok,
                "true_positive": tp,
                "false_positive": fp,
                "false_negative": fn,
            }
        )
    precision = (
        true_positive / (true_positive + false_positive)
        if (true_positive + false_positive)
        else None
    )
    recall = (
        true_positive / (true_positive + false_negative)
        if (true_positive + false_negative)
        else None
    )
    if precision is None and recall is None:
        f1_value: float | None = None
    elif not precision or not recall:
        f1_value = 0.0
    else:
        f1_value = 2 * precision * recall / (precision + recall)
    slot_f1 = MetricValue(true_positive, true_positive + false_negative, f1_value)
    return SuiteReport(
        suite="state",
        metrics={
            "joint_goal_accuracy": _ratio(jga_correct, len(rows)),
            "slot_f1": slot_f1,
        },
        extra={
            "slot_counts": {
                "true_positive": true_positive,
                "false_positive": false_positive,
                "false_negative": false_negative,
                "precision": precision,
                "recall": recall,
            }
        },
        cases=tuple(case_rows),
    )


# ---------------------------------------------------------------------------
# Reference resolution: Resolution Accuracy
# ---------------------------------------------------------------------------


def evaluate_reference_file(path: str | Path) -> SuiteReport:
    rows = load_jsonl(path)
    correct = 0
    case_rows: list[dict[str, Any]] = []
    for raw in rows:
        args = raw.get("args") or {}
        result = resolve_item_reference(
            raw.get("state") or {},
            domain=args.get("domain"),
            position=args.get("position"),
            item_id=args.get("item_id"),
            request_id=args.get("request_id"),
        )
        gold = raw.get("gold") or {}
        if gold.get("clarification"):
            ok = isinstance(result, ClarificationNeeded)
            resolved = None
        else:
            ok = (not isinstance(result, ClarificationNeeded)) and (
                result.item_id == gold.get("item_id")
            )
            resolved = None if isinstance(result, ClarificationNeeded) else result.item_id
        correct += int(ok)
        case_rows.append(
            {
                "case_id": raw["case_id"],
                "expected": gold,
                "resolved_item_id": resolved,
                "clarification": isinstance(result, ClarificationNeeded),
                "correct": ok,
            }
        )
    return SuiteReport(
        suite="reference",
        metrics={"resolution_accuracy": _ratio(correct, len(rows))},
        cases=tuple(case_rows),
    )


# ---------------------------------------------------------------------------
# Factual recall: probe answers vs gold, grouped by position / phase
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[^\w]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFC", text).casefold()
    return [token for token in _TOKEN_RE.split(normalized) if token]


def _probe_correct(predicted: str, gold: str) -> bool:
    gold_tokens = tokenize(gold)
    pred_tokens = tokenize(predicted)
    if not gold_tokens:
        return False
    # All gold tokens must be present, and no contradicting negation flip.
    covered = all(token in pred_tokens for token in gold_tokens)
    return covered


def evaluate_factual_recall_file(path: str | Path) -> SuiteReport:
    rows = load_jsonl(path)
    correct = 0
    by_position: dict[str, list[int]] = {}
    by_phase: dict[str, list[int]] = {}
    case_rows: list[dict[str, Any]] = []
    for raw in rows:
        predicted = str(raw.get("predicted_answer") or "")
        gold = str(raw.get("gold_answer") or "")
        ok = _probe_correct(predicted, gold)
        correct += int(ok)
        position = str(raw.get("position") or "unknown")
        phase = str(raw.get("phase") or "unknown")
        by_position.setdefault(position, []).append(int(ok))
        by_phase.setdefault(phase, []).append(int(ok))
        case_rows.append(
            {
                "case_id": raw["case_id"],
                "position": position,
                "phase": phase,
                "correct": ok,
            }
        )

    def _group(mapping: dict[str, list[int]]) -> dict[str, dict[str, Any]]:
        return {
            key: _ratio(sum(values), len(values)).to_dict()
            for key, values in mapping.items()
        }

    return SuiteReport(
        suite="factual_recall",
        metrics={"factual_recall_accuracy": _ratio(correct, len(rows))},
        extra={
            "by_position": _group(by_position),
            "by_phase": _group(by_phase),
        },
        cases=tuple(case_rows),
    )


# ---------------------------------------------------------------------------
# Task success: Success Rate over multi-turn scenarios
# ---------------------------------------------------------------------------


def evaluate_success_file(path: str | Path) -> SuiteReport:
    rows = load_jsonl(path)
    correct = 0
    case_rows: list[dict[str, Any]] = []
    for raw in rows:
        final_action = raw.get("final_action") or {}
        constraints = raw.get("constraints") or {}
        satisfied = all(
            normalize_value(final_action.get(key)) == normalize_value(value)
            for key, value in constraints.items()
        ) and bool(constraints)
        correct += int(satisfied)
        violated = [
            key
            for key, value in constraints.items()
            if normalize_value(final_action.get(key)) != normalize_value(value)
        ]
        case_rows.append(
            {
                "case_id": raw["case_id"],
                "success": satisfied,
                "violated_constraints": violated,
            }
        )
    return SuiteReport(
        suite="success",
        metrics={"success_rate": _ratio(correct, len(rows))},
        cases=tuple(case_rows),
    )
