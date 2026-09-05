from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from e2e_eval.schema import DEFAULT_FIXTURE_DIR, load_case, load_cases_from_dir

ALL_CASE_FILES = [
    "e2e_hotel_001.yaml",
    "e2e_flight_001.yaml",
    "e2e_car_001.yaml",
    "e2e_excursion_001.yaml",
    "e2e_override_hotel_001.yaml",
    "e2e_override_flight_001.yaml",
    "e2e_override_car_001.yaml",
    "e2e_override_excursion_001.yaml",
    "e2e_summary_hotel_001.yaml",
    "e2e_summary_flight_001.yaml",
    "e2e_summary_car_001.yaml",
    "e2e_summary_excursion_001.yaml",
    "e2e_multi_hotel_flight_001.yaml",
    "e2e_multi_flight_car_001.yaml",
    "e2e_multi_car_excursion_001.yaml",
    "e2e_multi_excursion_hotel_001.yaml",
    "e2e_write_hotel_001.yaml",
    "e2e_write_car_insert_001.yaml",
    "e2e_write_excursion_supersede_001.yaml",
    "e2e_write_global_name_001.yaml",
    "e2e_global_profile_name_001.yaml",
    "e2e_tools_all_001.yaml",
]

MULTI_CASE_IDS = {
    "e2e_multi_hotel_flight_001",
    "e2e_multi_flight_car_001",
    "e2e_multi_car_excursion_001",
    "e2e_multi_excursion_hotel_001",
}

SUMMARY_CASE_IDS = {
    "e2e_summary_hotel_001",
    "e2e_summary_flight_001",
    "e2e_summary_car_001",
    "e2e_summary_excursion_001",
}

WRITE_CASE_IDS = {
    "e2e_write_hotel_001",
    "e2e_write_car_insert_001",
    "e2e_write_excursion_supersede_001",
    "e2e_write_global_name_001",
}

TOOLS_ALL_CASE_ID = "e2e_tools_all_001"


@pytest.mark.parametrize("case_file", ALL_CASE_FILES)
def test_e2e_fixture_validates(case_file: str) -> None:
    case = load_case(DEFAULT_FIXTURE_DIR / case_file)
    assert case.id
    assert case.seed.long_term_memories
    assert case.expected_trace.expected_route
    assert case.input.messages
    if case.id in MULTI_CASE_IDS:
        assert len(case.expected_trace.expected_route) == 2
        assert len(case.expected_trace.expected_tools) == 2
    if case.id in SUMMARY_CASE_IDS:
        assert len(case.input.messages) == 3
        assert case.seed.thread_state.summary is None
        assert "summarize_conversation" in case.expected_trace.expected_node_sequence_contains
    if case.id in WRITE_CASE_IDS:
        assert len(case.input.messages) == 1
        assert "summarize_conversation" not in case.expected_trace.expected_node_sequence_contains
        assert "join_results" in case.expected_trace.expected_node_sequence_contains
        assert "memory_finalize" in case.expected_trace.expected_node_sequence_contains
        assert case.expected_finalize.action.value in {"NOOP", "INSERT", "SUPERSEDE"}
        assert case.expected_finalize.memories
    if case.id == TOOLS_ALL_CASE_ID:
        assert len(case.input.messages) == 4
        assert case.input.force_summarize_penultimate is False
        assert len(case.expected_trace.expected_tools) == 13
        assert case.expected_finalize.action.value == "NO_STORE"


def test_manifest_loads_all_cases() -> None:
    cases = load_cases_from_dir(DEFAULT_FIXTURE_DIR)
    assert len(cases) == 22
    assert {case.id for case in cases} == set(path.replace(".yaml", "") for path in ALL_CASE_FILES)
