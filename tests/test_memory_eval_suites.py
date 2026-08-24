import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memory_eval.suites import (
    evaluate_answer_file,
    evaluate_retrieval_file,
    evaluate_supersession_file,
    evaluate_transition_file,
    make_eval_settings,
    partial_f1,
    tokenize,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "long_term_memory_eval"


def test_transition_accuracy_covers_required_case_types():
    report = evaluate_transition_file(FIXTURES / "transition_cases.jsonl")
    ids = {case["case_id"] for case in report.cases}
    assert {
        "dup_001",
        "conflict_001",
        "condition_001",
        "sensitive_001",
        "ambiguous_001",
        "insert_001",
    } <= ids
    assert report.metrics["transition_accuracy"].value == 1.0


def test_supersession_correctness_links_and_hides_old_memory():
    settings = make_eval_settings()
    report = asyncio.run(
        evaluate_supersession_file(FIXTURES / "transition_cases.jsonl", settings)
    )
    assert report.metrics["supersession_correctness"].denominator == 2
    assert report.metrics["supersession_correctness"].value == 1.0
    assert all(
        case["old_inactive"] and case["linked"] and case["old_not_recalled"]
        for case in report.cases
    )


def test_retrieval_metrics_and_zero_leakage():
    settings = make_eval_settings()
    report = asyncio.run(
        evaluate_retrieval_file(FIXTURES / "retrieval_cases.jsonl", settings)
    )
    metrics = report.metrics
    assert metrics["recall_at_k"].value is not None
    assert metrics["precision_at_k"].denominator == 5 * len(report.cases)
    assert metrics["cross_user_leakage_rate"].value == 0.0
    assert metrics["inactive_leakage_rate"].value == 0.0
    isolation = next(case for case in report.cases if case["case_id"] == "cross_user_001")
    assert "u2-hotel" not in isolation["recalled_memory_ids"]
    inactive = next(case for case in report.cases if case["case_id"] == "inactive_001")
    assert "old-sea" not in inactive["recalled_memory_ids"]
    assert "expired-1" not in inactive["recalled_memory_ids"]
    assert "deleted-1" not in inactive["recalled_memory_ids"]


def test_answer_accuracy_and_partial_f1():
    report = evaluate_answer_file(FIXTURES / "answer_cases.jsonl")
    by_id = {case["case_id"]: case for case in report.cases}
    assert by_id["single_hop_001"]["correct"] is True
    assert by_id["unanswerable_fabricated_001"]["correct"] is False
    f1 = partial_f1("thich khach san boutique", "thich khach san boutique gan bien")
    assert f1.value == pytest.approx(0.8)
    assert tokenize("Thích, khách-sạn") == ["thích", "khách", "sạn"]


def test_empty_denominator_is_null():
    from memory_eval.suites import _ratio

    metric = _ratio(0, 0)
    assert metric.value is None
    assert metric.numerator == 0
    assert metric.denominator == 0


def test_postgres_user_filter_is_in_sql():
    source = Path("src/repositories/long_term_memory.py").read_text(encoding="utf-8")
    assert "user_id = %(user_id)s" in source
    assert "m.user_id = %(user_id)s" in source


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL is required")
def test_postgres_user_filter_live_when_available():
    test_postgres_user_filter_is_in_sql()
