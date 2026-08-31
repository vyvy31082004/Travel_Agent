from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memory_eval.threshold_analysis import (
    SweepMetrics,
    analyze_distance_scores,
    build_context_prompt_lookup,
    candidate_thresholds,
    estimate_context_tokens,
    select_pair_relative,
    sweep_threshold_grid,
    _compute_sweep_metrics,
    _index_records,
)
from settings import Settings


def make_settings(**overrides):
    values = dict(
        database_url="postgresql://user:pass@localhost/db",
        cookie_secret="secret",
        long_term_memory_recall_enabled=False,
        long_term_memory_write_enabled=False,
        long_term_memory_vector_distance_threshold=0.35,
    )
    values.update(overrides)
    return Settings(**values)


def sample_records() -> list[dict]:
    return [
        {
            "record_type": "case_summary",
            "case_id": "case_a",
            "gold_relevant_memory_ids": ["rel_a1", "rel_a2"],
            "gold_relevant_count": 2,
            "forbidden_memory_ids": ["forbidden_a"],
            "forbidden_reasons": {"forbidden_a": "inactive_status"},
            "expect_empty_recall": False,
        },
        {
            "record_type": "case_summary",
            "case_id": "case_b",
            "gold_relevant_memory_ids": [],
            "gold_relevant_count": 0,
            "forbidden_memory_ids": [],
            "forbidden_reasons": {},
            "expect_empty_recall": True,
        },
        {
            "record_type": "score",
            "case_id": "case_a",
            "fixture_memory_id": "rel_a1",
            "rank": 1,
            "cosine_distance": 0.10,
            "gold_relevant": True,
            "context_prompt_text": "[uuid-a1] relevant memory one",
        },
        {
            "record_type": "score",
            "case_id": "case_a",
            "fixture_memory_id": "noise_a",
            "rank": 2,
            "cosine_distance": 0.40,
            "gold_relevant": False,
            "context_prompt_text": "[uuid-noise-a] noisy memory text",
        },
        {
            "record_type": "not_returned",
            "case_id": "case_a",
            "fixture_memory_id": "rel_a2",
            "gold_relevant": True,
        },
        {
            "record_type": "score",
            "case_id": "case_b",
            "fixture_memory_id": "noise_b",
            "rank": 1,
            "cosine_distance": 0.20,
            "gold_relevant": False,
            "context_prompt_text": "[uuid-noise-b] another noisy memory",
        },
    ]


def test_recall_denominator_uses_case_summary_not_score_rows():
    _, summaries, scores_by_case = _index_records(sample_records())
    prompt_lookup = build_context_prompt_lookup(sample_records())
    metrics = _compute_sweep_metrics(
        summaries, scores_by_case, tau=0.5, k=2, prompt_lookup=prompt_lookup
    )
    assert metrics.recall_at_k == pytest.approx(0.5)


def test_context_precision_uses_actual_returns_not_fixed_k():
    _, summaries, scores_by_case = _index_records(sample_records())
    prompt_lookup = build_context_prompt_lookup(sample_records())
    metrics = _compute_sweep_metrics(
        summaries, scores_by_case, tau=0.5, k=1, prompt_lookup=prompt_lookup
    )
    # case_a returns one relevant memory; case_b returns one irrelevant memory.
    assert metrics.context_precision == pytest.approx(0.5)
    assert metrics.memory_per_query == pytest.approx(1.0)


def test_spurious_recall_counts_zero_gold_case_with_return():
    _, summaries, scores_by_case = _index_records(sample_records())
    prompt_lookup = build_context_prompt_lookup(sample_records())
    metrics = _compute_sweep_metrics(
        summaries, scores_by_case, tau=0.5, k=1, prompt_lookup=prompt_lookup
    )
    assert metrics.spurious_recall_rate == pytest.approx(1.0)


def test_tokens_per_query_reflects_returned_context():
    _, summaries, scores_by_case = _index_records(sample_records())
    prompt_lookup = build_context_prompt_lookup(sample_records())
    metrics = _compute_sweep_metrics(
        summaries, scores_by_case, tau=0.5, k=1, prompt_lookup=prompt_lookup
    )
    expected_case_a = estimate_context_tokens("[uuid-a1] relevant memory one")
    expected_case_b = estimate_context_tokens("[uuid-noise-b] another noisy memory")
    assert metrics.total_context_tokens == expected_case_a + expected_case_b
    assert metrics.tokens_per_query == pytest.approx(
        (expected_case_a + expected_case_b) / 2
    )


def test_sweep_grid_includes_all_k_values():
    metrics = sweep_threshold_grid(sample_records(), tau_values=[0.35], k_values=[1, 3, 5, 7])
    assert {metric.k for metric in metrics} == {1, 3, 5, 7}


def test_select_pair_relative_prefers_low_spurious_within_recall_band():
    metrics = [
        SweepMetrics(
            tau=0.30,
            k=5,
            recall_at_k=0.90,
            spurious_recall_rate=0.10,
            context_precision=0.8,
            memory_per_query=2.0,
            tokens_per_query=40.0,
            total_context_tokens=80,
            cross_user_leakage_rate=0.0,
            inactive_leakage_rate=0.0,
        ),
        SweepMetrics(
            tau=0.35,
            k=3,
            recall_at_k=0.895,
            spurious_recall_rate=0.0,
            context_precision=0.7,
            memory_per_query=1.5,
            tokens_per_query=30.0,
            total_context_tokens=60,
            cross_user_leakage_rate=0.0,
            inactive_leakage_rate=0.0,
        ),
    ]
    selected = select_pair_relative(metrics)
    assert selected["selected_pair"] == {"tau": 0.35, "k": 3}


def test_select_pair_rejects_non_zero_leakage():
    metrics = [
        SweepMetrics(
            tau=0.35,
            k=5,
            recall_at_k=1.0,
            spurious_recall_rate=0.0,
            context_precision=0.9,
            memory_per_query=1.0,
            tokens_per_query=20.0,
            total_context_tokens=40,
            cross_user_leakage_rate=0.1,
            inactive_leakage_rate=0.0,
        )
    ]
    with pytest.raises(ValueError, match="zero leakage"):
        select_pair_relative(metrics)


def test_candidate_thresholds_include_default():
    distribution = {
        "relevant": {"p75": 0.34, "p90": 0.41},
        "irrelevant": {"p25": 0.36},
    }
    candidates = candidate_thresholds(distribution, default_tau=0.35)
    sources = {item["source"] for item in candidates}
    assert "current_default" in sources
    assert any(item["tau"] == pytest.approx(0.35) for item in candidates)


def test_analyze_distance_scores_end_to_end():
    report = analyze_distance_scores(sample_records(), settings=make_settings())
    assert report["eval_branch"] == "pgvector_semantic_only"
    assert len(report["threshold_sweep"]) == len(report["candidate_thresholds"]) * 10
    assert "selected_pair" in report
    assert report["distance_distribution"]["relevant"]["count"] == 1
    first_row = report["threshold_sweep"][0]
    assert "tokens_per_query" in first_row
    assert "total_context_tokens" in first_row


def test_cli_main_preserves_retrieval_threshold_jsonl(tmp_path, monkeypatch):
    from memory_eval.cli import main

    jsonl_path = tmp_path / "scores.jsonl"
    expected = '{"record_type":"run_metadata","eval_branch":"pgvector_semantic_only"}\n'

    async def fake_evaluate_suite(args):
        jsonl_path.write_text(expected, encoding="utf-8")
        return {
            "suite": "retrieval-threshold",
            "mode": "collect",
            "output_path": str(jsonl_path),
        }

    def fake_run_async(coro):
        import asyncio

        return asyncio.run(coro)

    monkeypatch.setattr("memory_eval.cli.evaluate_suite", fake_evaluate_suite)
    monkeypatch.setattr("memory_eval.cli._run_async", fake_run_async)

    assert (
        main(
            [
                "--suite",
                "retrieval-threshold",
                "--split",
                "development",
                "--output",
                str(jsonl_path),
            ]
        )
        == 0
    )
    assert jsonl_path.read_text(encoding="utf-8") == expected
