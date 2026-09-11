"""Unit tests for STM live schema, scoring bridge, and CLI wiring (no Gemini)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memory_eval.cli import build_parser, main as memory_eval_main
from memory_eval.stm_live import (
    LiveCaseObservation,
    observation_to_score_rows,
    require_gemini_api_key,
    score_stm_live_from_observations,
)
from memory_eval.stm_live_schema import (
    DEV_COUNT,
    TEST_COUNT,
    TOTAL_COUNT,
    load_cases_from_dir,
    validate_manifest_counts,
)

LIVE_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "short_term_memory_live"


def test_manifest_counts_20_30():
    counts = validate_manifest_counts(LIVE_FIXTURES)
    assert counts == {
        "total": TOTAL_COUNT,
        "development": DEV_COUNT,
        "test": TEST_COUNT,
    }
    assert TEST_COUNT == 30
    assert TOTAL_COUNT == 50


def test_split_filters():
    all_cases = load_cases_from_dir(LIVE_FIXTURES, split="all")
    dev = load_cases_from_dir(LIVE_FIXTURES, split="development")
    test = load_cases_from_dir(LIVE_FIXTURES, split="test")
    assert len(all_cases) == TOTAL_COUNT
    assert len(dev) == DEV_COUNT
    assert len(test) == TEST_COUNT
    assert {c.split for c in dev} == {"development"}
    assert {c.split for c in test} == {"test"}


def test_cases_cover_live_metric_families():
    cases = load_cases_from_dir(LIVE_FIXTURES, split="all")
    covered: set[str] = set()
    for case in cases:
        covered.update(case.metrics)
    assert covered == {"reference", "factual_recall", "success"}


def test_score_bridge_with_mocked_observations():
    cases = load_cases_from_dir(LIVE_FIXTURES, split="development")
    observations: list[LiveCaseObservation] = []
    for case in cases:
        state: dict = {}
        probe = ""
        search_arguments: dict = {}
        if "reference" in case.metrics and case.reference:
            state = {**(case.reference.seed_visible_state or {})}
        if "factual_recall" in case.metrics:
            probe = case.gold_answer or ""
        if "success" in case.metrics and case.constraints:
            # Simulate Result Store / MCP args (location alias for destination).
            search_arguments = dict(case.constraints)
            if "destination" in search_arguments:
                search_arguments["location"] = search_arguments["destination"]
        observations.append(
            LiveCaseObservation(
                case_id=case.id,
                metrics=list(case.metrics),
                final_state=state,
                probe_answer=probe,
                search_arguments=search_arguments,
            )
        )

    payload = score_stm_live_from_observations(
        cases,
        observations,
        fixtures=LIVE_FIXTURES,
        split="development",
    )
    assert payload["suite"] == "stm-live"
    assert payload["case_count"] == DEV_COUNT
    metrics = payload["report"]["metrics"]
    assert "joint_goal_accuracy" not in metrics
    assert "slot_f1" not in metrics
    assert metrics["resolution_accuracy"]["value"] == 1.0
    assert metrics["factual_recall_accuracy"]["value"] == 1.0
    assert metrics["success_rate"]["value"] == 1.0


def test_success_scores_from_search_argument_aliases():
    cases = [
        case
        for case in load_cases_from_dir(LIVE_FIXTURES, split="development")
        if "success" in case.metrics
    ]
    observations = []
    for case in cases:
        raw_args = {}
        for key, value in (case.constraints or {}).items():
            if key == "destination":
                raw_args["location"] = value
            elif key == "check_in":
                raw_args["checkin_date"] = value
            elif key == "check_out":
                raw_args["checkout_date"] = value
            elif key == "date":
                raw_args["start_date"] = value
            else:
                raw_args[key] = value
        observations.append(
            LiveCaseObservation(
                case_id=case.id,
                metrics=list(case.metrics),
                search_arguments=raw_args,
            )
        )

    payload = score_stm_live_from_observations(
        cases,
        observations,
        fixtures=LIVE_FIXTURES,
        split="development",
    )
    assert payload["report"]["metrics"]["success_rate"]["value"] == 1.0


def test_success_accepts_iata_and_car_tool_args():
    """Live MCP args often use IATA / start_ms / address instead of gold city labels."""
    cases = {
        case.id: case
        for case in load_cases_from_dir(LIVE_FIXTURES, split="development")
        if case.id
        in {"stm_live_success_flight_002", "stm_live_success_car_003"}
    }
    observations = [
        LiveCaseObservation(
            case_id="stm_live_success_flight_002",
            metrics=["success"],
            search_arguments={
                "adults": 2,
                "origin": "SGN",
                "departure_date": "2026-10-11",
                "stops": "0",
                "destination": "CXR",
            },
        ),
        LiveCaseObservation(
            case_id="stm_live_success_car_003",
            metrics=["success"],
            search_arguments={
                "address": "Sân bay Phú Bài, Huế",
                "user_needs": "xe 4 chỗ đón tại sân bay, trả tại Huế ngày 12/10/2026",
                "end_ms": "2026-10-12 20:00",
                "start_ms": "2026-10-12 08:00",
            },
        ),
    ]
    payload = score_stm_live_from_observations(
        [cases["stm_live_success_flight_002"], cases["stm_live_success_car_003"]],
        observations,
        fixtures=LIVE_FIXTURES,
        split="development",
    )
    assert payload["report"]["metrics"]["success_rate"]["value"] == 1.0
    by_id = {row["case_id"]: row for row in payload["report"]["success"]["cases"]}
    assert by_id["stm_live_success_flight_002"]["success"] is True
    assert by_id["stm_live_success_car_003"]["success"] is True


def test_factual_recall_matches_accentless_and_numeric_money_gold():
    cases = load_cases_from_dir(LIVE_FIXTURES, split="development")
    factual_cases = [case for case in cases if "factual_recall" in case.metrics]
    observations = [
        LiveCaseObservation(
            case_id="stm_live_factual_001",
            metrics=["factual_recall"],
            probe_answer="Ngân sách là dưới 2.000.000 VNĐ/đêm.",
        ),
        LiveCaseObservation(
            case_id="stm_live_factual_002",
            metrics=["factual_recall"],
            probe_answer="Giới hạn transit là tối đa 3 giờ.",
        ),
        LiveCaseObservation(
            case_id="stm_live_factual_003",
            metrics=["factual_recall"],
            probe_answer="Tour phù hợp nhất kéo dài khoảng 4 tiếng.",
        ),
        LiveCaseObservation(
            case_id="stm_live_factual_004",
            metrics=["factual_recall"],
            probe_answer="Có, bạn có yêu cầu ghế trẻ em.",
        ),
        LiveCaseObservation(
            case_id="stm_live_factual_005",
            metrics=["factual_recall"],
            probe_answer="Ngân sách khách sạn là dưới 2.000.000 VNĐ mỗi đêm.",
        ),
    ]
    payload = score_stm_live_from_observations(
        factual_cases,
        observations,
        fixtures=LIVE_FIXTURES,
        split="development",
    )
    assert payload["report"]["metrics"]["factual_recall_accuracy"]["value"] == 1.0


def test_observation_to_score_rows_skips_on_error():
    case = load_cases_from_dir(LIVE_FIXTURES, split="development")[0]
    obs = LiveCaseObservation(
        case_id=case.id,
        metrics=list(case.metrics),
        error="RuntimeError: boom",
    )
    buckets = observation_to_score_rows(case, obs)
    assert buckets["reference"] == []
    assert buckets["factual_recall"] == []
    assert buckets["success"] == []
    assert "state" not in buckets


def test_require_gemini_api_key_fails_clearly(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY or GEMINI_API_KEY"):
        require_gemini_api_key()


def test_cli_parser_includes_stm_live():
    parser = build_parser()
    args = parser.parse_args(["--suite", "stm-live", "--split", "development", "--no-report"])
    assert args.suite == "stm-live"
    assert args.split == "development"


def test_offline_stm_all_still_works(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    code = memory_eval_main(
        ["--suite", "stm-all", "--split", "development", "--no-report"]
    )
    assert code == 0
