import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memory_eval.short_term import (
    _ratio,
    evaluate_factual_recall_file,
    evaluate_reference_file,
    evaluate_state_file,
    evaluate_success_file,
    normalize_value,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "short_term_memory_eval"


def test_empty_denominator_is_null():
    metric = _ratio(0, 0)
    assert metric.value is None
    assert metric.numerator == 0
    assert metric.denominator == 0


def test_normalize_value_dates_numbers_bool():
    assert normalize_value("15/09/2026") == "2026-09-15"
    assert normalize_value("2026-09-15") == "2026-09-15"
    assert normalize_value(2000000) == "2000000"
    assert normalize_value("2.000.000") == "2000000"
    assert normalize_value(True) == "true"


def test_state_jga_and_slot_f1():
    report = evaluate_state_file(FIXTURES / "state_cases.jsonl")
    by_id = {case["case_id"]: case for case in report.cases}
    # Full-match turn counts, one-slot-wrong turn fails JGA.
    assert by_id["state_full_001"]["joint_correct"] is True
    assert by_id["state_one_slot_wrong_001"]["joint_correct"] is False
    # Normalized date makes the slot match.
    assert by_id["state_normalized_date_001"]["joint_correct"] is True
    # Extra non-gold slot (pets) counts as false positive but not false negative.
    assert by_id["state_extra_slot_001"]["false_positive"] >= 1
    jga = report.metrics["joint_goal_accuracy"]
    assert jga.denominator == 5
    assert 0.0 <= jga.value <= 1.0
    slot_f1 = report.metrics["slot_f1"]
    assert slot_f1.value is not None


def test_one_slot_wrong_produces_false_positive_and_negative():
    report = evaluate_state_file(FIXTURES / "state_cases.jsonl")
    case = next(c for c in report.cases if c["case_id"] == "state_one_slot_wrong_001")
    # guests slot: predicted 3 vs gold 2 → one FP and one FN.
    assert case["false_positive"] >= 1
    assert case["false_negative"] >= 1


def test_reference_resolution_accuracy_and_clarification():
    report = evaluate_reference_file(FIXTURES / "reference_cases.jsonl")
    by_id = {case["case_id"]: case for case in report.cases}
    assert by_id["ref_ordinal_001"]["resolved_item_id"] == "hotel_2"
    assert by_id["ref_ordinal_001"]["correct"] is True
    assert by_id["ref_ambiguous_001"]["clarification"] is True
    assert by_id["ref_ambiguous_001"]["correct"] is True
    assert by_id["ref_out_of_range_001"]["correct"] is True
    acc = report.metrics["resolution_accuracy"]
    assert acc.denominator == 5


def test_factual_recall_grouping_and_correctness():
    report = evaluate_factual_recall_file(FIXTURES / "factual_recall_cases.jsonl")
    by_id = {case["case_id"]: case for case in report.cases}
    assert by_id["recall_mid_after_001"]["correct"] is True
    assert by_id["recall_mid_lost_001"]["correct"] is False
    positions = report.extra["by_position"]
    phases = report.extra["by_phase"]
    assert set(positions) >= {"đầu", "giữa", "cuối"}
    assert set(phases) >= {"before", "after"}
    assert report.metrics["factual_recall_accuracy"].denominator == 6


def test_success_rate_and_violation():
    report = evaluate_success_file(FIXTURES / "success_cases.jsonl")
    by_id = {case["case_id"]: case for case in report.cases}
    assert by_id["success_full_001"]["success"] is True
    assert by_id["success_change_mind_001"]["success"] is True
    assert by_id["success_violation_001"]["success"] is False
    assert "date" in by_id["success_violation_001"]["violated_constraints"]
    rate = report.metrics["success_rate"]
    assert rate.numerator == 3
    assert rate.denominator == 4
