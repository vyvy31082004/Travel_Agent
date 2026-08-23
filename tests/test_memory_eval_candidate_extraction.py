import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memory_eval.candidate_extraction import (
    CandidateExtractionEvaluator,
    load_candidate_extraction_cases,
)


FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "long_term_memory_eval"
    / "extraction_cases.jsonl"
)


def test_gold_fixture_has_traceability_and_expected_splits():
    cases = load_candidate_extraction_cases(FIXTURE)
    assert len(cases) >= 50
    assert {case.split for case in cases} == {"development", "test"}
    assert all(case.requirement_id for case in cases)
    assert all(case.rationale for case in cases)
    assert all(case.code_path for case in cases)
    assert all(case.metric for case in cases)


def test_candidate_extraction_report_has_all_requested_metrics():
    cases = load_candidate_extraction_cases(FIXTURE)
    report = asyncio.run(CandidateExtractionEvaluator().evaluate(cases))
    metrics = report.metrics()
    assert set(metrics) == {
        "extraction_precision",
        "extraction_recall",
        "evidence_faithfulness_rate",
        "category_accuracy",
        "domain_accuracy",
        "family_accuracy",
        "unsafe_rejection_rate",
    }
    assert report.total_cases == len(cases)
    assert report.total_gold_memories > 0
    assert report.unsafe_gold_cases > 0
    assert all(0 <= metric.value <= 1 for metric in metrics.values() if metric.value is not None)


def test_unsafe_rejection_metric_is_measured_without_hard_coding_target():
    cases = load_candidate_extraction_cases(FIXTURE)
    report = asyncio.run(CandidateExtractionEvaluator().evaluate(cases))
    metric = report.unsafe_rejection_rate
    assert metric.value is not None
    assert metric.denominator == sum(case.unsafe for case in cases)
    assert metric.numerator == sum(
        case.correctly_rejected_unsafe is True for case in report.cases
    )
    assert 0 <= metric.value <= 1


def test_atomic_gold_cases_are_reported_as_recall_failures_when_baseline_merges_facts():
    cases = load_candidate_extraction_cases(FIXTURE)
    report = asyncio.run(CandidateExtractionEvaluator().evaluate(cases))
    atomic = next(case for case in report.cases if case.case_id == "atomic_001")
    assert len(atomic.matched_gold_indices) < 3
    assert report.extraction_recall.value is not None


def test_zero_denominator_is_undefined_not_zero():
    from memory_eval.candidate_extraction import CandidateExtractionReport

    report = CandidateExtractionReport(
        total_cases=0,
        total_extracted_memories=0,
        valid_extracted_memories=0,
        correctly_extracted_gold_memories=0,
        total_gold_memories=0,
        memories_supported_by_user_evidence=0,
        approved_memories=0,
        category_correct=0,
        category_labeled_cases=0,
        domain_correct=0,
        domain_labeled_cases=0,
        family_correct=0,
        family_labeled_cases=0,
        correctly_rejected_unsafe_cases=0,
        unsafe_gold_cases=0,
    )
    assert report.extraction_precision.value is None
    assert report.extraction_recall.value is None
    assert report.unsafe_rejection_rate.value is None
