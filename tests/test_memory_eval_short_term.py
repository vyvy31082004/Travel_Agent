import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memory_eval.cli import main as memory_eval_main
from memory_eval.short_term import (
    DEV_COUNT,
    TEST_COUNT,
    _ratio,
    evaluate_factual_recall_file,
    evaluate_reference_file,
    evaluate_state_file,
    evaluate_success_file,
    normalize_value,
)
from memory_eval.stm_report import (
    default_stm_report_paths,
    render_stm_report_markdown,
    write_stm_reports,
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


def test_fixture_split_sizes():
    for name in (
        "state_cases.jsonl",
        "reference_cases.jsonl",
        "factual_recall_cases.jsonl",
        "success_cases.jsonl",
    ):
        rows = [
            json.loads(line)
            for line in (FIXTURES / name).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(rows) == DEV_COUNT + TEST_COUNT
        assert sum(1 for r in rows if r["split"] == "development") == DEV_COUNT
        assert sum(1 for r in rows if r["split"] == "test") == TEST_COUNT


def test_state_jga_and_slot_f1():
    report = evaluate_state_file(FIXTURES / "state_cases.jsonl")
    by_id = {case["case_id"]: case for case in report.cases}
    assert by_id["state_full_001"]["joint_correct"] is True
    assert by_id["state_one_slot_wrong_001"]["joint_correct"] is False
    assert by_id["state_normalized_date_001"]["joint_correct"] is True
    assert by_id["state_extra_slot_001"]["false_positive"] >= 1
    jga = report.metrics["joint_goal_accuracy"]
    assert jga.denominator == DEV_COUNT + TEST_COUNT
    assert 0.0 <= jga.value <= 1.0
    assert report.metrics["slot_f1"].value is not None


def test_state_split_filter():
    dev = evaluate_state_file(FIXTURES / "state_cases.jsonl", split="development")
    test = evaluate_state_file(FIXTURES / "state_cases.jsonl", split="test")
    assert len(dev.cases) == DEV_COUNT
    assert len(test.cases) == TEST_COUNT


def test_one_slot_wrong_produces_false_positive_and_negative():
    report = evaluate_state_file(FIXTURES / "state_cases.jsonl")
    case = next(c for c in report.cases if c["case_id"] == "state_one_slot_wrong_001")
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
    assert acc.denominator == DEV_COUNT + TEST_COUNT


def test_factual_recall_grouping_and_correctness():
    report = evaluate_factual_recall_file(FIXTURES / "factual_recall_cases.jsonl")
    by_id = {case["case_id"]: case for case in report.cases}
    assert by_id["recall_mid_after_001"]["correct"] is True
    assert by_id["recall_mid_lost_001"]["correct"] is False
    positions = report.extra["by_position"]
    phases = report.extra["by_phase"]
    assert set(positions) >= {"đầu", "giữa", "cuối"}
    assert set(phases) >= {"before", "after"}
    assert report.metrics["factual_recall_accuracy"].denominator == DEV_COUNT + TEST_COUNT


def test_success_rate_and_violation():
    report = evaluate_success_file(FIXTURES / "success_cases.jsonl")
    by_id = {case["case_id"]: case for case in report.cases}
    assert by_id["success_full_001"]["success"] is True
    assert by_id["success_change_mind_001"]["success"] is True
    assert by_id["success_violation_001"]["success"] is False
    assert "date" in by_id["success_violation_001"]["violated_constraints"]
    rate = report.metrics["success_rate"]
    assert rate.denominator == DEV_COUNT + TEST_COUNT
    assert rate.numerator < rate.denominator


def test_stm_report_writer(tmp_path: Path):
    payload = {
        "suite": "stm-all",
        "split": "development",
        "case_count": DEV_COUNT * 4,
        "gold_path": str(FIXTURES),
        "report": {
            "metrics": {
                "joint_goal_accuracy": {"numerator": 1, "denominator": 2, "value": 0.5},
                "slot_f1": {"numerator": 1, "denominator": 2, "value": 0.5},
                "resolution_accuracy": {"numerator": 1, "denominator": 1, "value": 1.0},
                "factual_recall_accuracy": {
                    "numerator": 1,
                    "denominator": 1,
                    "value": 1.0,
                },
                "success_rate": {"numerator": 1, "denominator": 1, "value": 1.0},
            }
        },
    }
    json_path = tmp_path / "stm.json"
    md_path = tmp_path / "stm.md"
    write_stm_reports(payload, json_path=json_path, md_path=md_path)
    assert json_path.exists()
    md = md_path.read_text(encoding="utf-8")
    assert "Short-term memory evaluation" in md
    assert "Joint Goal Accuracy" in md
    default_json, default_md = default_stm_report_paths(split="test", suite="stm-all")
    assert default_json.name == "short_term_memory_stm_all_test.json"
    assert default_md.name == "short_term_memory_stm_all_test.md"
    assert "Joint Goal Accuracy (JGA)" in render_stm_report_markdown(payload)


def test_cli_stm_all_writes_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    out = tmp_path / "stm_dev.json"
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    rc = memory_eval_main(
        [
            "--suite",
            "stm-all",
            "--split",
            "development",
            "--output",
            str(out),
        ]
    )
    assert rc == 0
    assert out.exists()
    assert out.with_suffix(".md").exists()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["suite"] == "stm-all"
    assert payload["split"] == "development"
    assert payload["case_count"] == DEV_COUNT * 4
