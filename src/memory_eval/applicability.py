from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from memory.applicability import ApplicabilityLabel, MockApplicabilityJudge
from memory_eval.common import load_jsonl


@dataclass
class ApplicabilityEvalResult:
    case_id: str
    memory_id: str
    expected: str
    actual: str
    passed: bool


async def evaluate_applicability_file(
    path: Path,
    *,
    split: str = "all",
) -> dict[str, Any]:
    rows = load_jsonl(path)
    if split != "all":
        rows = [row for row in rows if row.get("split", "development") == split]

    results: list[ApplicabilityEvalResult] = []
    for row in rows:
        overrides = {
            item["memory_id"]: ApplicabilityLabel(item["expected_label"])
            for item in row.get("memories", [])
        }
        judge = MockApplicabilityJudge(overrides=overrides)
        from memory.long_term import TravelMemory

        candidates = [
            TravelMemory(
                memory_id=item["memory_id"],
                user_id=row.get("user_id", "user-1"),
                memory_text=item["memory_text"],
                category=item.get("category", "hotel_preference"),
                domain=row.get("domain", "hotel"),
                evidence_text=item.get("evidence_text", item["memory_text"]),
                source_thread_id="eval",
            )
            for item in row.get("memories", [])
        ]
        judgments = await judge.judge_batch(
            user_query=row["query"],
            domain=row["domain"],
            domain_action=row.get("action", "general"),
            domain_state=row.get("domain_state") or {},
            candidates=candidates,
        )
        by_id = {item.memory_id: str(item.label) for item in judgments}
        for item in row.get("memories", []):
            expected = item["expected_label"]
            actual = by_id.get(item["memory_id"], "missing")
            results.append(
                ApplicabilityEvalResult(
                    case_id=row["case_id"],
                    memory_id=item["memory_id"],
                    expected=expected,
                    actual=actual,
                    passed=actual == expected,
                )
            )

    passed = sum(1 for item in results if item.passed)
    total = len(results) or 1
    return {
        "suite": "applicability",
        "split": split,
        "accuracy": passed / total,
        "passed": passed,
        "total": len(results),
        "results": [item.__dict__ for item in results],
    }


def write_applicability_report(payload: dict[str, Any], output: Path) -> None:
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
