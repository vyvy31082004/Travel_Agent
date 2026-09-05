from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from e2e_eval.auto_scorer import score_trace
from e2e_eval.schema import DEFAULT_FIXTURE_DIR, ScoreStatus, load_case


@pytest.fixture
def hotel_case():
    return load_case(DEFAULT_FIXTURE_DIR / "e2e_hotel_001.yaml")


def _base_trace() -> dict:
    return {
        "global_recall": {
            "recalled_fixture_ids": [],
        },
        "primary_route": {
            "delegated_domains": ["hotel"],
            "node_updates": [
                "memory_recall_global",
                "primary_assistant",
                "hotel_assistant",
                "join_results",
                "memory_finalize",
            ],
        },
        "domain_recall": {
            "hotel": {
                "candidate_pool_ids": ["m_budget", "m_quiet", "m_beach"],
                "applicability": {
                    "m_budget": "apply",
                    "m_quiet": "apply",
                    "m_beach": "apply",
                },
                "final_context_ids": ["m_budget", "m_quiet", "m_beach"],
            }
        },
        "tools": [
            {
                "name": "search_hotels_tool",
                "arguments": {
                    "destination": "Phu Quoc",
                    "check_in": "2026-09-01",
                    "check_out": "2026-09-03",
                },
            }
        ],
        "finalize": {"db_mutations": []},
    }


def test_auto_scorer_passes_ideal_trace(hotel_case) -> None:
    scores = score_trace(hotel_case, _base_trace())
    assert scores.routing_accuracy.status == ScoreStatus.PASS
    assert scores.tool_call_correctness.status == ScoreStatus.PASS
    assert scores.context_recall_precision.status == ScoreStatus.PASS
    assert scores.cross_user_inactive_leakage.status == ScoreStatus.PASS
    assert scores.finalize_correctness.status == ScoreStatus.PASS
    assert scores.trace_integrity.status == ScoreStatus.PASS


def test_auto_scorer_fails_routing_mismatch(hotel_case) -> None:
    trace = _base_trace()
    trace["primary_route"]["delegated_domains"] = ["flight"]
    scores = score_trace(hotel_case, trace)
    assert scores.routing_accuracy.status == ScoreStatus.FAIL
    assert scores.trace_integrity.status == ScoreStatus.FAIL


def test_auto_scorer_fails_leakage(hotel_case) -> None:
    trace = _base_trace()
    trace["domain_recall"]["hotel"]["final_context_ids"].append("m_other_user")
    trace["domain_recall"]["hotel"]["applicability"]["m_other_user"] = "apply"
    scores = score_trace(hotel_case, trace)
    assert scores.context_recall_precision.status == ScoreStatus.FAIL
    assert scores.cross_user_inactive_leakage.status == ScoreStatus.FAIL


def test_auto_scorer_accepts_location_as_destination(hotel_case) -> None:
    trace = _base_trace()
    trace["tools"] = [
        {
            "name": "search_hotels_tool",
            "arguments": {"location": "Phu Quoc"},
        }
    ]
    scores = score_trace(hotel_case, trace)
    assert scores.tool_call_correctness.status == ScoreStatus.PASS


def test_auto_scorer_uses_last_complete_tool_call(hotel_case) -> None:
    trace = _base_trace()
    trace["tools"] = [
        {
            "name": "search_hotels_tool",
            "arguments": {"destination": "Hanoi"},
        },
        {
            "name": "search_hotels_tool",
            "arguments": {
                "destination": "Da Nang",
                "check_in": "2026-10-10",
                "check_out": "2026-10-12",
            },
        },
        {
            "name": "search_hotels_tool",
            "arguments": {},
            "inferred": True,
        },
    ]
    scores = score_trace(hotel_case, trace)
    assert scores.tool_call_correctness.status == ScoreStatus.PASS


@pytest.fixture
def car_case():
    return load_case(DEFAULT_FIXTURE_DIR / "e2e_car_001.yaml")


def test_auto_scorer_accepts_car_mcp_argument_names(car_case) -> None:
    trace = {
        "global_recall": {"recalled_fixture_ids": []},
        "primary_route": {"delegated_domains": ["car"], "node_updates": []},
        "domain_recall": {
            "car": {
                "candidate_pool_ids": ["m_automatic", "m_seats", "m_surcharge"],
                "applicability": {
                    "m_automatic": "apply",
                    "m_seats": "apply",
                    "m_surcharge": "apply",
                },
                "final_context_ids": ["m_automatic", "m_seats", "m_surcharge"],
            }
        },
        "tools": [
            {
                "name": "search_cars_tool",
                "arguments": {
                    "address": "Da Nang",
                    "start_ms": "2026-10-10 08:00",
                    "end_ms": "2026-10-13 20:00",
                },
            }
        ],
        "finalize": {"db_mutations": []},
    }
    scores = score_trace(car_case, trace)
    assert scores.tool_call_correctness.status == ScoreStatus.PASS


def test_auto_scorer_fails_missing_tool(hotel_case) -> None:
    trace = _base_trace()
    trace["tools"] = []
    scores = score_trace(hotel_case, trace)
    assert scores.tool_call_correctness.status == ScoreStatus.FAIL


@pytest.fixture
def multi_hotel_flight_case():
    return load_case(DEFAULT_FIXTURE_DIR / "e2e_multi_hotel_flight_001.yaml")


def _multi_hotel_flight_trace() -> dict:
    return {
        "global_recall": {"recalled_fixture_ids": []},
        "primary_route": {
            "delegated_domains": ["flight", "hotel"],
            "node_updates": [
                "memory_recall_global",
                "primary_assistant",
                "flight_assistant",
                "hotel_assistant",
                "join_results",
                "memory_finalize",
            ],
        },
        "join": {
            "branch_count": 2,
            "merged_domains": ["flight", "hotel"],
        },
        "domain_recall": {
            "flight": {
                "candidate_pool_ids": ["m_flight_economy", "m_flight_nonstop"],
                "applicability": {
                    "m_flight_economy": "apply",
                    "m_flight_nonstop": "apply",
                },
                "final_context_ids": ["m_flight_economy", "m_flight_nonstop"],
            },
            "hotel": {
                "candidate_pool_ids": ["m_hotel_budget", "m_hotel_quiet"],
                "applicability": {
                    "m_hotel_budget": "apply",
                    "m_hotel_quiet": "apply",
                },
                "final_context_ids": ["m_hotel_budget", "m_hotel_quiet"],
            },
        },
        "tools": [
            {
                "name": "search_one_way_flights_tool",
                "arguments": {
                    "origin": "SGN",
                    "destination": "DAD",
                    "departure_date": "2026-10-10",
                },
            },
            {
                "name": "search_hotels_tool",
                "arguments": {"destination": "Da Nang"},
            },
        ],
        "finalize": {"db_mutations": []},
    }


def test_auto_scorer_passes_multi_domain_trace(multi_hotel_flight_case) -> None:
    scores = score_trace(multi_hotel_flight_case, _multi_hotel_flight_trace())
    assert scores.routing_accuracy.status == ScoreStatus.PASS
    assert scores.tool_call_correctness.status == ScoreStatus.PASS
    assert scores.context_recall_precision.status == ScoreStatus.PASS
    assert scores.cross_user_inactive_leakage.status == ScoreStatus.PASS
    assert scores.join_integrity.status == ScoreStatus.PASS
    assert scores.trace_integrity.status == ScoreStatus.PASS


def test_auto_scorer_fails_cross_domain_leakage(multi_hotel_flight_case) -> None:
    trace = _multi_hotel_flight_trace()
    trace["domain_recall"]["flight"]["final_context_ids"].append("m_hotel_budget")
    trace["domain_recall"]["flight"]["applicability"]["m_hotel_budget"] = "apply"
    scores = score_trace(multi_hotel_flight_case, trace)
    assert scores.context_recall_precision.status == ScoreStatus.FAIL
    assert scores.cross_user_inactive_leakage.status == ScoreStatus.FAIL


def test_auto_scorer_fails_join_integrity(multi_hotel_flight_case) -> None:
    trace = _multi_hotel_flight_trace()
    trace["join"]["merged_domains"] = ["flight"]
    trace["join"]["branch_count"] = 1
    scores = score_trace(multi_hotel_flight_case, trace)
    assert scores.join_integrity.status == ScoreStatus.FAIL
    assert scores.trace_integrity.status == ScoreStatus.FAIL


@pytest.fixture
def override_hotel_case():
    return load_case(DEFAULT_FIXTURE_DIR / "e2e_override_hotel_001.yaml")


def _override_hotel_trace() -> dict:
    return {
        "global_recall": {"recalled_fixture_ids": []},
        "primary_route": {"delegated_domains": ["hotel"], "node_updates": []},
        "execution_path": [
            {"seq": 1, "node": "memory_recall_global", "tools": []},
            {"seq": 2, "node": "primary_assistant", "tools": []},
            {"seq": 3, "node": "hotel_assistant", "tools": []},
            {"seq": 4, "node": "memory_recall_hotel", "tools": []},
            {"seq": 5, "node": "hotel_chat", "tools": []},
            {
                "seq": 6,
                "node": "search_hotels_tool",
                "tools": [{"name": "search_hotels_tool", "arguments": {}}],
            },
            {"seq": 7, "node": "join_results", "tools": []},
            {"seq": 8, "node": "primary_assistant", "tools": []},
            {"seq": 9, "node": "memory_finalize", "tools": []},
        ],
        "domain_recall": {
            "hotel": {
                "candidate_pool_ids": ["m_budget", "m_quiet"],
                "applicability": {
                    "m_budget": "overridden",
                    "m_quiet": "uncertain",
                },
                "final_context_ids": ["m_quiet"],
            }
        },
        "tools": [
            {
                "name": "search_hotels_tool",
                "arguments": {
                    "destination": "Da Nang",
                    "check_in": "2026-10-10",
                    "check_out": "2026-10-12",
                },
            }
        ],
        "finalize": {"db_mutations": []},
    }


def test_auto_scorer_scores_applicability(override_hotel_case) -> None:
    scores = score_trace(override_hotel_case, _override_hotel_trace())
    assert scores.applicability_correctness.status == ScoreStatus.PASS
    assert scores.execution_path.status == ScoreStatus.PASS
    assert scores.trace_integrity.status == ScoreStatus.PASS


def test_auto_scorer_fails_applicability_mismatch(override_hotel_case) -> None:
    trace = _override_hotel_trace()
    trace["domain_recall"]["hotel"]["applicability"]["m_budget"] = "apply"
    scores = score_trace(override_hotel_case, trace)
    assert scores.applicability_correctness.status == ScoreStatus.FAIL


def test_auto_scorer_fails_execution_path_order(override_hotel_case) -> None:
    trace = _override_hotel_trace()
    trace["execution_path"] = trace["execution_path"][:6]
    scores = score_trace(override_hotel_case, trace)
    assert scores.execution_path.status == ScoreStatus.FAIL


def test_auto_scorer_summary_hotel_path_and_context() -> None:
    case = load_case(DEFAULT_FIXTURE_DIR / "e2e_summary_hotel_001.yaml")
    trace = {
        "global_recall": {"recalled_fixture_ids": []},
        "primary_route": {"delegated_domains": ["hotel"], "node_updates": []},
        "execution_path": [
            {"seq": 1, "node": "memory_recall_global", "tools": []},
            {"seq": 2, "node": "primary_assistant", "tools": []},
            {"seq": 3, "node": "summarize_conversation", "tools": []},
            {"seq": 4, "node": "memory_finalize", "tools": []},
            {"seq": 5, "node": "memory_recall_global", "tools": []},
            {"seq": 6, "node": "primary_assistant", "tools": []},
            {"seq": 7, "node": "hotel_assistant", "tools": []},
            {"seq": 8, "node": "memory_recall_hotel", "tools": []},
            {"seq": 9, "node": "hotel_chat", "tools": []},
            {
                "seq": 10,
                "node": "search_hotels_tool",
                "tools": [{"name": "search_hotels_tool", "arguments": {}}],
            },
            {"seq": 11, "node": "join_results", "tools": []},
            {"seq": 12, "node": "primary_assistant", "tools": []},
            {"seq": 13, "node": "memory_finalize", "tools": []},
        ],
        "domain_recall": {
            "hotel": {
                "candidate_pool_ids": ["m_quiet", "m_avoid_groups"],
                "applicability": {
                    "m_quiet": "uncertain",
                    "m_avoid_groups": "uncertain",
                },
                "final_context_ids": ["m_quiet", "m_avoid_groups"],
            }
        },
        "tools": [
            {
                "name": "search_hotels_tool",
                "arguments": {
                    "destination": "Da Nang",
                    "check_in": "2026-10-10",
                    "check_out": "2026-10-12",
                },
            }
        ],
        "finalize": {"db_mutations": []},
        "stm": {"summary": "Ở Đà Nẵng 10–12/10, 2 người.", "message_count": 2},
    }
    scores = score_trace(case, trace)
    assert scores.routing_accuracy.status == ScoreStatus.PASS
    assert scores.tool_call_correctness.status == ScoreStatus.PASS
    assert scores.context_recall_precision.status == ScoreStatus.PASS
    assert scores.applicability_correctness.status == ScoreStatus.PASS
    assert scores.execution_path.status == ScoreStatus.PASS
    assert scores.finalize_correctness.status == ScoreStatus.PASS
    assert scores.trace_integrity.status == ScoreStatus.PASS


def _write_hotel_path() -> list[dict]:
    return [
        {"seq": 1, "node": "memory_recall_global", "tools": []},
        {"seq": 2, "node": "primary_assistant", "tools": []},
        {"seq": 3, "node": "hotel_assistant", "tools": []},
        {"seq": 4, "node": "memory_recall_hotel", "tools": []},
        {"seq": 5, "node": "hotel_chat", "tools": []},
        {
            "seq": 6,
            "node": "search_hotels_tool",
            "tools": [{"name": "search_hotels_tool", "arguments": {}}],
        },
        {"seq": 7, "node": "join_results", "tools": []},
        {"seq": 8, "node": "primary_assistant", "tools": []},
        {"seq": 9, "node": "memory_finalize", "tools": []},
    ]


def test_auto_scorer_write_hotel_noop_pass() -> None:
    case = load_case(DEFAULT_FIXTURE_DIR / "e2e_write_hotel_001.yaml")
    quiet_id = "uuid-quiet"
    trace = {
        "metadata": {"fixture_to_uuid": {"m_quiet": quiet_id}},
        "global_recall": {"recalled_fixture_ids": []},
        "primary_route": {"delegated_domains": ["hotel"], "node_updates": []},
        "execution_path": _write_hotel_path(),
        "domain_recall": {
            "hotel": {
                "candidate_pool_ids": ["m_quiet"],
                "applicability": {"m_quiet": "uncertain"},
                "final_context_ids": ["m_quiet"],
            }
        },
        "tools": [
            {
                "name": "search_hotels_tool",
                "arguments": {
                    "destination": "Da Nang",
                    "check_in": "2026-10-10",
                    "check_out": "2026-10-12",
                    "adults": 2,
                },
            }
        ],
        "finalize": {
            "db_mutations": [],
            "memory_job": {"status": "completed"},
            "audits": [
                {
                    "decision": "noop",
                    "proposed_transition": {
                        "existing_memory_id": quiet_id,
                        "reasons": ["relation_equivalent"],
                    },
                    "affected_memory_ids": [quiet_id],
                }
            ],
            "seeded_status": {"m_quiet": {"status": "active", "memory_id": quiet_id}},
        },
    }
    scores = score_trace(case, trace)
    assert scores.finalize_correctness.status == ScoreStatus.PASS
    assert scores.applicability_correctness.status == ScoreStatus.PASS
    assert scores.execution_path.status == ScoreStatus.PASS
    assert scores.trace_integrity.status == ScoreStatus.PASS


def test_auto_scorer_write_hotel_skipped_job_fails() -> None:
    case = load_case(DEFAULT_FIXTURE_DIR / "e2e_write_hotel_001.yaml")
    trace = {
        "metadata": {"fixture_to_uuid": {"m_quiet": "uuid-quiet"}},
        "global_recall": {"recalled_fixture_ids": []},
        "primary_route": {"delegated_domains": ["hotel"], "node_updates": []},
        "execution_path": _write_hotel_path(),
        "domain_recall": {
            "hotel": {
                "candidate_pool_ids": ["m_quiet"],
                "applicability": {"m_quiet": "uncertain"},
                "final_context_ids": ["m_quiet"],
            }
        },
        "tools": [
            {
                "name": "search_hotels_tool",
                "arguments": {
                    "location": "Da Nang",
                    "checkin_date": "2026-10-10",
                    "checkout_date": "2026-10-12",
                    "guests": 2,
                },
            }
        ],
        "finalize": {
            "db_mutations": [],
            "memory_job": {"status": "skipped"},
            "audits": [],
            "seeded_status": {"m_quiet": {"status": "active"}},
        },
    }
    scores = score_trace(case, trace)
    assert scores.finalize_correctness.status == ScoreStatus.FAIL
    assert scores.trace_integrity.status == ScoreStatus.FAIL


def test_auto_scorer_write_car_two_inserts_pass() -> None:
    case = load_case(DEFAULT_FIXTURE_DIR / "e2e_write_car_insert_001.yaml")
    trace = {
        "global_recall": {"recalled_fixture_ids": []},
        "primary_route": {"delegated_domains": ["car"], "node_updates": []},
        "execution_path": [
            {"seq": 1, "node": "memory_recall_global", "tools": []},
            {"seq": 2, "node": "primary_assistant", "tools": []},
            {"seq": 3, "node": "car_assistant", "tools": []},
            {"seq": 4, "node": "memory_recall_car", "tools": []},
            {"seq": 5, "node": "car_chat", "tools": []},
            {
                "seq": 6,
                "node": "search_cars_tool",
                "tools": [{"name": "search_cars_tool", "arguments": {}}],
            },
            {"seq": 7, "node": "join_results", "tools": []},
            {"seq": 8, "node": "primary_assistant", "tools": []},
            {"seq": 9, "node": "memory_finalize", "tools": []},
        ],
        "domain_recall": {
            "car": {
                "candidate_pool_ids": [],
                "applicability": {},
                "final_context_ids": [],
            }
        },
        "tools": [
            {
                "name": "search_cars_tool",
                "arguments": {
                    "address": "Da Nang",
                    "start_ms": "2026-10-10 08:00",
                    "end_ms": "2026-10-12 20:00",
                },
            }
        ],
        "finalize": {
            "memory_job": {"status": "completed"},
            "db_mutations": [
                {
                    "memory_id": "new-1",
                    "memory_text": "Ưu tiên xe 5 chỗ",
                    "category": "car_preference",
                    "domain": "car",
                    "family": "travel_preferences",
                },
                {
                    "memory_id": "new-2",
                    "memory_text": "Ưu tiên số tự động",
                    "category": "car_preference",
                    "domain": "car",
                    "family": "travel_preferences",
                },
            ],
            "audits": [],
            "seeded_status": {},
        },
    }
    scores = score_trace(case, trace)
    assert scores.finalize_correctness.status == ScoreStatus.PASS
    assert scores.trace_integrity.status == ScoreStatus.PASS


def test_auto_scorer_write_car_noop_fails() -> None:
    case = load_case(DEFAULT_FIXTURE_DIR / "e2e_write_car_insert_001.yaml")
    trace = {
        "global_recall": {"recalled_fixture_ids": []},
        "primary_route": {"delegated_domains": ["car"], "node_updates": []},
        "execution_path": [
            {"seq": 1, "node": "memory_recall_global", "tools": []},
            {"seq": 2, "node": "primary_assistant", "tools": []},
            {"seq": 3, "node": "car_assistant", "tools": []},
            {"seq": 4, "node": "memory_recall_car", "tools": []},
            {"seq": 5, "node": "car_chat", "tools": []},
            {
                "seq": 6,
                "node": "search_cars_tool",
                "tools": [{"name": "search_cars_tool", "arguments": {}}],
            },
            {"seq": 7, "node": "join_results", "tools": []},
            {"seq": 8, "node": "primary_assistant", "tools": []},
            {"seq": 9, "node": "memory_finalize", "tools": []},
        ],
        "domain_recall": {
            "car": {"candidate_pool_ids": [], "applicability": {}, "final_context_ids": []}
        },
        "tools": [
            {
                "name": "search_cars_tool",
                "arguments": {
                    "location": "Da Nang",
                    "pickup_date": "2026-10-10",
                    "return_date": "2026-10-12",
                },
            }
        ],
        "finalize": {
            "memory_job": {"status": "completed"},
            "db_mutations": [],
            "audits": [
                {
                    "decision": "noop",
                    "proposed_transition": {"reasons": ["exact_duplicate"]},
                }
            ],
        },
    }
    scores = score_trace(case, trace)
    assert scores.finalize_correctness.status == ScoreStatus.FAIL


def test_auto_scorer_write_excursion_supersede_pass() -> None:
    case = load_case(DEFAULT_FIXTURE_DIR / "e2e_write_excursion_supersede_001.yaml")
    old_id = "uuid-large"
    new_id = "uuid-small"
    trace = {
        "metadata": {"fixture_to_uuid": {"m_large_group": old_id}},
        "global_recall": {"recalled_fixture_ids": []},
        "primary_route": {"delegated_domains": ["excursion"], "node_updates": []},
        "execution_path": [
            {"seq": 1, "node": "memory_recall_global", "tools": []},
            {"seq": 2, "node": "primary_assistant", "tools": []},
            {"seq": 3, "node": "excursion_assistant", "tools": []},
            {"seq": 4, "node": "memory_recall_excursion", "tools": []},
            {"seq": 5, "node": "excursion_chat", "tools": []},
            {
                "seq": 6,
                "node": "search_attractions_tool",
                "tools": [
                    {
                        "name": "search_attractions_tool",
                        "sub_steps": ["searchLocation", "searchAttractions"],
                    }
                ],
            },
            {"seq": 7, "node": "join_results", "tools": []},
            {"seq": 8, "node": "primary_assistant", "tools": []},
            {"seq": 9, "node": "memory_finalize", "tools": []},
        ],
        "domain_recall": {
            "excursion": {
                "candidate_pool_ids": ["m_large_group"],
                "applicability": {"m_large_group": "overridden"},
                "final_context_ids": [],
            }
        },
        "tools": [
            {
                "name": "search_attractions_tool",
                "arguments": {"location": "Hoi An", "date": "2026-10-12"},
            }
        ],
        "finalize": {
            "memory_job": {"status": "completed"},
            "db_mutations": [
                {
                    "memory_id": new_id,
                    "memory_text": "Ưu tiên tour nhóm nhỏ",
                    "category": "excursion_preference",
                    "domain": "excursion",
                    "family": "travel_preferences",
                    "supersedes_memory_id": old_id,
                }
            ],
            "seeded_status": {
                "m_large_group": {"status": "superseded", "memory_id": old_id}
            },
        },
    }
    scores = score_trace(case, trace)
    assert scores.finalize_correctness.status == ScoreStatus.PASS
    assert scores.applicability_correctness.status == ScoreStatus.PASS
    assert scores.execution_path.status == ScoreStatus.PASS
    assert scores.trace_integrity.status == ScoreStatus.PASS


def test_auto_scorer_write_global_name_insert_and_forbidden_arg() -> None:
    case = load_case(DEFAULT_FIXTURE_DIR / "e2e_write_global_name_001.yaml")
    path = _write_hotel_path()
    recall = {
        "hotel": {
            "candidate_pool_ids": [],
            "applicability": {},
            "final_context_ids": [],
        }
    }
    finalize = {
        "memory_job": {"status": "completed"},
        "db_mutations": [
            {
                "memory_id": "name-1",
                "memory_text": "Quỳnh Anh",
                "category": "profile_fact",
                "domain": "general",
                "family": "profile_facts",
            }
        ],
    }
    passing = {
        "global_recall": {"recalled_fixture_ids": []},
        "primary_route": {"delegated_domains": ["hotel"], "node_updates": []},
        "execution_path": path,
        "domain_recall": recall,
        "tools": [
            {
                "name": "search_hotels_tool",
                "arguments": {
                    "destination": "Da Nang",
                    "check_in": "2026-10-10",
                    "check_out": "2026-10-12",
                },
            }
        ],
        "finalize": finalize,
    }
    scores = score_trace(case, passing)
    assert scores.finalize_correctness.status == ScoreStatus.PASS
    assert scores.tool_call_correctness.status == ScoreStatus.PASS

    leaking = dict(passing)
    leaking["tools"] = [
        {
            "name": "search_hotels_tool",
            "arguments": {
                "destination": "Da Nang",
                "check_in": "2026-10-10",
                "check_out": "2026-10-12",
                "guest_name": "Quỳnh Anh",
            },
        }
    ]
    scores = score_trace(case, leaking)
    assert scores.tool_call_correctness.status == ScoreStatus.FAIL
    assert scores.trace_integrity.status == ScoreStatus.FAIL


def _global_profile_name_trace() -> dict:
    return {
        "global_recall": {"recalled_fixture_ids": ["m_name"]},
        "primary_route": {"delegated_domains": ["hotel"], "node_updates": []},
        "execution_path": [
            {"seq": 1, "node": "memory_recall_global", "tools": []},
            {"seq": 2, "node": "primary_assistant", "tools": []},
            {"seq": 3, "node": "hotel_assistant", "tools": []},
            {"seq": 4, "node": "memory_recall_hotel", "tools": []},
            {"seq": 5, "node": "hotel_chat", "tools": []},
            {
                "seq": 6,
                "node": "search_hotels_tool",
                "tools": [{"name": "search_hotels_tool", "arguments": {}}],
            },
            {"seq": 7, "node": "join_results", "tools": []},
            {"seq": 8, "node": "primary_assistant", "tools": []},
            {"seq": 9, "node": "memory_finalize", "tools": []},
        ],
        "domain_recall": {
            "hotel": {
                "candidate_pool_ids": [],
                "applicability": {},
                "final_context_ids": [],
            }
        },
        "tools": [
            {
                "name": "search_hotels_tool",
                "arguments": {
                    "destination": "Da Nang",
                    "check_in": "2026-10-10",
                    "check_out": "2026-10-12",
                    "adults": 2,
                },
            }
        ],
        "finalize": {"db_mutations": []},
    }


def test_auto_scorer_global_profile_name_passes() -> None:
    case = load_case(DEFAULT_FIXTURE_DIR / "e2e_global_profile_name_001.yaml")
    scores = score_trace(case, _global_profile_name_trace())
    assert scores.routing_accuracy.status == ScoreStatus.PASS
    assert scores.tool_call_correctness.status == ScoreStatus.PASS
    assert scores.context_recall_precision.status == ScoreStatus.PASS
    assert scores.finalize_correctness.status == ScoreStatus.PASS
    assert scores.trace_integrity.status == ScoreStatus.PASS


def test_auto_scorer_global_profile_name_fails_name_in_tool() -> None:
    case = load_case(DEFAULT_FIXTURE_DIR / "e2e_global_profile_name_001.yaml")
    trace = _global_profile_name_trace()
    trace["tools"][0]["arguments"]["guest_name"] = "chị Lan"
    scores = score_trace(case, trace)
    assert scores.tool_call_correctness.status == ScoreStatus.FAIL


def test_auto_scorer_global_profile_name_fails_hotel_noise_leakage() -> None:
    case = load_case(DEFAULT_FIXTURE_DIR / "e2e_global_profile_name_001.yaml")
    trace = _global_profile_name_trace()
    trace["domain_recall"]["hotel"]["applicability"]["m_hotel_other_user"] = "apply"
    trace["domain_recall"]["hotel"]["final_context_ids"].append("m_hotel_other_user")
    scores = score_trace(case, trace)
    assert scores.context_recall_precision.status == ScoreStatus.FAIL


def _tools_all_trace() -> dict:
    return {
        "global_recall": {"recalled_fixture_ids": []},
        "primary_route": {
            "delegated_domains": ["flight"],
            "node_updates": [
                "memory_recall_global",
                "primary_assistant",
                "hotel_assistant",
                "car_assistant",
                "excursion_assistant",
                "flight_assistant",
                "memory_finalize",
            ],
        },
        "domain_recall": {
            "flight": {
                "candidate_pool_ids": ["m_flight_economy", "m_flight_nonstop"],
                "applicability": {
                    "m_flight_economy": "apply",
                    "m_flight_nonstop": "apply",
                },
                "final_context_ids": ["m_flight_economy", "m_flight_nonstop"],
            }
        },
        "tools": [
            {
                "name": "search_hotels_tool",
                "arguments": {"location": "Da Nang"},
            },
            {
                "name": "get_hotel_room_list_tool",
                "arguments": {
                    "hotel_id": "16256042",
                    "checkin_date": "2026-10-10",
                    "checkout_date": "2026-10-12",
                },
            },
            {
                "name": "get_hotel_reviews_tool",
                "arguments": {"hotel_id": "16256042"},
            },
            {
                "name": "get_hotel_facility_tool",
                "arguments": {"hotel_id": "16256042"},
            },
            {
                "name": "get_hotel_policy_tool",
                "arguments": {"hotel_id": "16256042"},
            },
            {
                "name": "search_cars_tool",
                "arguments": {
                    "address": "Da Nang",
                    "start_ms": "2026-10-10 10:00",
                    "end_ms": "2026-10-12 10:00",
                },
            },
            {
                "name": "get_car_details_tool",
                "arguments": {"car_id": "c1", "car_name": "Xpander"},
            },
            {
                "name": "search_attractions_tool",
                "arguments": {"location": "Da Nang"},
            },
            {
                "name": "fetch_attraction_details_tool",
                "arguments": {"slug": "ba-na-hills"},
            },
            {
                "name": "fetch_attraction_reviews_tool",
                "arguments": {"id": "attr-1"},
            },
            {
                "name": "search_one_way_flights_tool",
                "arguments": {
                    "origin": "SGN",
                    "destination": "DAD",
                    "departure_date": "2026-10-10",
                },
            },
            {
                "name": "search_round_trip_flights_tool",
                "arguments": {
                    "origin": "SGN",
                    "destination": "DAD",
                    "departure_date": "2026-10-10",
                },
            },
            {
                "name": "book_flight_by_id",
                "arguments": {"flight_id": "FL-A8B2C"},
            },
        ],
        "execution_path": [
            {"node": "memory_recall_global", "tools": []},
            {"node": "primary_assistant", "tools": []},
            {"node": "hotel_assistant", "tools": []},
            {"node": "car_assistant", "tools": []},
            {"node": "excursion_assistant", "tools": []},
            {"node": "flight_assistant", "tools": []},
            {"node": "memory_finalize", "tools": []},
        ],
        "finalize": {"db_mutations": []},
    }


def test_auto_scorer_tools_all_passes_with_accumulated_tools() -> None:
    case = load_case(DEFAULT_FIXTURE_DIR / "e2e_tools_all_001.yaml")
    scores = score_trace(case, _tools_all_trace())
    assert scores.tool_call_correctness.status == ScoreStatus.PASS
    assert scores.routing_accuracy.status == ScoreStatus.PASS
    assert scores.execution_path.status == ScoreStatus.PASS
    assert scores.trace_integrity.status == ScoreStatus.PASS


def test_auto_scorer_tools_all_fails_when_early_tool_missing() -> None:
    case = load_case(DEFAULT_FIXTURE_DIR / "e2e_tools_all_001.yaml")
    trace = _tools_all_trace()
    trace["tools"] = [
        entry
        for entry in trace["tools"]
        if entry["name"] != "search_hotels_tool"
    ]
    scores = score_trace(case, trace)
    assert scores.tool_call_correctness.status == ScoreStatus.FAIL

