import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memory_eval.common import load_jsonl
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
SMOKE_IDS = {
    "dup_001",
    "conflict_001",
    "condition_001",
    "sensitive_001",
    "ambiguous_001",
    "insert_001",
}
REQUIRED_REQUIREMENTS = {
    "REQ-TRANS-DUP",
    "REQ-TRANS-CONFLICT",
    "REQ-TRANS-CONDITION",
    "REQ-TRANS-SENSITIVE",
    "REQ-TRANS-AMBIGUOUS",
    "REQ-TRANS-INSERT",
}


def test_transition_gold_has_splits_and_traceability():
    rows = load_jsonl(FIXTURES / "transition_cases.jsonl")
    assert len(rows) == 150
    assert sum(1 for row in rows if row["split"] == "development") == 65
    assert sum(1 for row in rows if row["split"] == "test") == 85
    assert {row["split"] for row in rows} == {"development", "test"}
    assert REQUIRED_REQUIREMENTS <= {row["requirement_id"] for row in rows}
    assert all(row.get("rationale") for row in rows)
    assert all(row.get("code_path") for row in rows)
    assert all(row.get("metric") for row in rows)
    assert SMOKE_IDS <= {row["case_id"] for row in rows}
    for req in REQUIRED_REQUIREMENTS:
        req_rows = [row for row in rows if row["requirement_id"] == req]
        assert {row["split"] for row in req_rows} == {"development", "test"}

    manifest = json.loads(
        (FIXTURES / "transition_split_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["development_count"] == 65
    assert manifest["test_count"] == 85
    assert len(manifest["mapping"]) == 150


def test_transition_accuracy_covers_required_case_types():
    path = FIXTURES / "transition_cases.jsonl"
    # Policy-mock exercises the semantic transition policy without an LLM.
    report = asyncio.run(
        evaluate_transition_file(path, transition_path="policy-mock")
    )
    ids = {case["case_id"] for case in report.cases}
    assert SMOKE_IDS <= ids
    assert len(report.cases) == 150
    by_id = {case["case_id"]: case for case in report.cases}
    assert all(by_id[case_id]["correct"] for case_id in SMOKE_IDS)
    assert report.metrics["transition_accuracy"].denominator == 150

    dev = asyncio.run(
        evaluate_transition_file(
            path, split="development", transition_path="policy-mock"
        )
    )
    assert dev.metrics["transition_accuracy"].value == 1.0

    # Lexical path: exact-dup / reject still work; polarity conflicts become INSERT.
    lexical_dev = asyncio.run(
        evaluate_transition_file(
            path, split="development", transition_path="lexical"
        )
    )
    lexical_by_id = {case["case_id"]: case for case in lexical_dev.cases}
    assert lexical_by_id["dup_001"]["correct"] is True
    assert lexical_by_id["conflict_001"]["predicted_action"] == "insert"
    assert lexical_by_id["sensitive_001"]["correct"] is True

    held = asyncio.run(
        evaluate_transition_file(path, split="test", transition_path="lexical")
    )
    assert held.metrics["transition_accuracy"].denominator == 85
    held_acc = held.metrics["transition_accuracy"].value
    assert held_acc is not None
    assert 0.35 <= held_acc <= 0.85


def test_transition_split_filter_scopes_cases_and_supersession():
    settings = make_eval_settings()
    path = FIXTURES / "transition_cases.jsonl"
    rows = load_jsonl(path)
    for split, expected_count in (("development", 65), ("test", 85)):
        report = asyncio.run(
            evaluate_transition_file(
                path, split=split, transition_path="policy-mock"
            )
        )
        assert len(report.cases) == expected_count
        supersede_count = sum(
            1
            for row in rows
            if row["split"] == split and row["gold_action"] == "supersede"
        )
        super_report = asyncio.run(
            evaluate_supersession_file(
                path, settings, split=split, transition_path="policy-mock"
            )
        )
        assert super_report.metrics["supersession_correctness"].denominator == (
            supersede_count
        )
        assert len(super_report.cases) == supersede_count


def test_supersession_correctness_links_and_hides_old_memory():
    settings = make_eval_settings()
    path = FIXTURES / "transition_cases.jsonl"
    # Policy-mock predicts SUPERSEDE so commit path can be validated end-to-end.
    dev = asyncio.run(
        evaluate_supersession_file(
            path, settings, split="development", transition_path="policy-mock"
        )
    )
    assert dev.metrics["supersession_correctness"].denominator == 18
    assert dev.metrics["supersession_correctness"].value == 1.0
    assert all(
        case["old_inactive"] and case["linked"] and case["old_not_recalled"]
        for case in dev.cases
    )
    held = asyncio.run(
        evaluate_supersession_file(
            path, settings, split="test", transition_path="policy-mock"
        )
    )
    assert held.metrics["supersession_correctness"].denominator == 25
    assert held.metrics["supersession_correctness"].value == 1.0


REQUIRED_RETRIEVAL_REQUIREMENTS = {
    "REQ-RETR-SCOPE-SAME",
    "REQ-RETR-SCOPE-CROSS-USER",
    "REQ-RETR-SCOPE-CROSS-DOMAIN",
    "REQ-RETR-SCOPE-INACTIVE",
    "REQ-RETR-SCOPE-GLOBAL",
    "REQ-RETR-SCOPE-EMPTY",
    "REQ-RETR-ACTION-HOTEL",
    "REQ-RETR-ACTION-FLIGHT",
    "REQ-RETR-ACTION-CAR",
    "REQ-RETR-ACTION-EXCURSION",
    "REQ-RETR-OVERRIDE",
    "REQ-RETR-SOFT-PREF",
    "REQ-RETR-STATE",
}
RETRIEVAL_SMOKE_IDS = {
    "scope_same_user_same_domain_dev_00",
    "scope_cross_user_dev_00",
    "action_contrast_hotel_search_dev_00",
    "override_flight_time_dev_00",
    "soft_hotel_quiet_uncertain_dev_00",
    "state_hotel_bathtub_apply_with_selection_dev_00",
}


def test_retrieval_gold_has_splits_and_traceability():
    from memory_eval.retrieval_schema import SCENARIO_TYPES, validate_dataset

    rows = load_jsonl(FIXTURES / "retrieval_cases.jsonl")
    assert not validate_dataset(rows)
    assert len(rows) == 150
    assert sum(1 for row in rows if row["split"] == "development") == 65
    assert sum(1 for row in rows if row["split"] == "test") == 85
    assert {row["split"] for row in rows} == {"development", "test"}
    assert REQUIRED_RETRIEVAL_REQUIREMENTS <= {row["requirement_id"] for row in rows}
    assert all(row.get("rationale") for row in rows)
    assert all(row.get("code_path") for row in rows)
    assert all(row.get("metric") for row in rows)
    assert all(row.get("scenario_type") for row in rows)
    assert RETRIEVAL_SMOKE_IDS <= {row["case_id"] for row in rows}
    for req in REQUIRED_RETRIEVAL_REQUIREMENTS:
        req_rows = [row for row in rows if row["requirement_id"] == req]
        assert {row["split"] for row in req_rows} == {"development", "test"}

    manifest = json.loads(
        (FIXTURES / "retrieval_split_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["development_count"] == 65
    assert manifest["test_count"] == 85
    assert len(manifest["mapping"]) == 150
    assert manifest["coverage_gaps"] == []
    for scenario_type in SCENARIO_TYPES:
        counts = manifest["coverage_matrix"][scenario_type]
        assert counts["development"] >= 1
        assert counts["test"] >= 1


def test_retrieval_metrics_and_zero_leakage():
    settings = make_eval_settings()
    report = asyncio.run(
        evaluate_retrieval_file(
            FIXTURES / "retrieval_cases.jsonl",
            settings,
            retrieval_path="inmemory",
        )
    )
    metrics = report.metrics
    assert len(report.cases) == 150
    assert metrics["candidate_pool_completeness"].value == 1.0
    assert metrics["cross_user_candidate_leakage"].value == 0.0
    assert metrics["cross_domain_candidate_leakage"].value == 0.0
    assert metrics["inactive_candidate_leakage"].value == 0.0
    assert all(case["sql_pool_ok"] for case in report.cases)

    isolation = next(
        case for case in report.cases if case["case_id"] == "scope_cross_user_dev_00"
    )
    assert isolation["expected_pool"] == ["scope_xuser_dev_00-a1"]
    inactive = next(
        case for case in report.cases if case["case_id"] == "scope_inactive_dev_00"
    )
    assert "scope_inact_dev_00-old" not in inactive["actual_pool"]

    dev = asyncio.run(
        evaluate_retrieval_file(
            FIXTURES / "retrieval_cases.jsonl",
            settings,
            split="development",
            retrieval_path="inmemory",
        )
    )
    assert dev.metrics["candidate_pool_completeness"].value == 1.0
    assert dev.metrics["overridden_leakage_rate"].value == 0.0
    assert dev.metrics["cross_user_candidate_leakage"].value == 0.0


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


@pytest.mark.skipif(
    not os.getenv("RUN_POSTGRES_INTEGRATION"),
    reason="RUN_POSTGRES_INTEGRATION required",
)
def test_postgres_user_filter_live_when_available():
    test_postgres_user_filter_is_in_sql()
