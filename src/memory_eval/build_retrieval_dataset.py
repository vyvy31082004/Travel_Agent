"""Build retrieval_cases.jsonl (150 cases) and retrieval_split_manifest.json.

Run from repo root:
  python -m memory_eval.build_retrieval_dataset
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from memory_eval.retrieval_schema import (
    GROUP_BY_SCENARIO,
    REQUIREMENT_BY_SCENARIO,
    SCENARIO_TYPES,
    build_manifest,
    validate_dataset,
)

FIXTURE_DIR = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "long_term_memory_eval"
)

FAMILY_BY_CATEGORY = {
    "hotel_preference": "travel_preferences",
    "flight_preference": "travel_preferences",
    "car_preference": "travel_preferences",
    "excursion_preference": "travel_preferences",
    "general_preference": "travel_preferences",
    "profile_fact": "profile_facts",
}

# (development_count, test_count) per scenario_type — totals 65 / 85
SPLIT_COUNTS: dict[str, tuple[int, int]] = {
    "scope_same_user_same_domain": (2, 3),
    "scope_cross_user": (2, 3),
    "scope_cross_domain": (2, 3),
    "scope_inactive": (2, 3),
    "scope_global_not_in_pool": (2, 3),
    "scope_empty_pool": (2, 3),
    "action_contrast_hotel_search": (1, 3),
    "action_contrast_hotel_details": (1, 2),
    "action_contrast_hotel_select_room": (2, 2),
    "action_contrast_hotel_reviews": (1, 2),
    "action_contrast_flight_search": (2, 2),
    "action_contrast_flight_compare": (1, 2),
    "action_contrast_car_search": (2, 2),
    "action_contrast_car_select": (1, 2),
    "action_contrast_excursion_search": (2, 2),
    "action_contrast_excursion_details": (1, 2),
    "override_flight_time": (2, 3),
    "override_hotel_budget": (2, 3),
    "override_hotel_location_uncertain": (2, 3),
    "override_car_transmission": (2, 3),
    "override_flight_departure": (2, 3),
    "soft_hotel_quiet_uncertain": (3, 3),
    "soft_hotel_avoid_groups_uncertain": (3, 3),
    "soft_hotel_bathtub_uncertain": (3, 3),
    "soft_flight_direct_apply": (3, 4),
    "soft_flight_lowest_price_uncertain": (2, 3),
    "state_hotel_bathtub_apply_with_selection": (4, 4),
    "state_hotel_bathtub_irrelevant_without_selection": (4, 4),
    "state_flight_seat_with_shortlist": (4, 4),
    "state_car_capacity_with_trip_context": (3, 3),
}

CODE_PATH = [
    "MemoryService.fetch_domain_candidates",
    "MemoryService.recall_domain_with_applicability",
]
METRICS = [
    "candidate_pool_completeness",
    "context_recall",
    "context_precision",
    "applicability_macro_f1",
    "overridden_leakage_rate",
    "cross_domain_candidate_leakage",
]


def _mem(
    memory_id: str,
    *,
    user_id: str,
    text: str,
    domain: str,
    category: str | None = None,
    status: str = "active",
    thread_id: str = "t-eval",
) -> dict[str, Any]:
    category = category or f"{domain}_preference"
    if domain == "general":
        category = "profile_fact"
    return {
        "memory_id": memory_id,
        "user_id": user_id,
        "memory_text": text,
        "category": category,
        "domain": domain,
        "family": FAMILY_BY_CATEGORY.get(category, "travel_preferences"),
        "evidence_text": text,
        "source_thread_id": thread_id,
        "status": status,
    }


def _case(
    *,
    case_id: str,
    split: str,
    scenario_type: str,
    user_id: str,
    user_query: str,
    domain: str,
    memory_store: list[dict[str, Any]],
    expected_sql_pool: list[str],
    expected_applicability: dict[str, str],
    expected_action: str | None = None,
    domain_state: dict[str, Any] | None = None,
    global_context: dict[str, Any] | None = None,
    expected_presented_constraints: list[dict[str, Any]] | None = None,
    rationale: str = "",
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "split": split,
        "scenario_type": scenario_type,
        "group": GROUP_BY_SCENARIO[scenario_type],
        "requirement_id": REQUIREMENT_BY_SCENARIO[scenario_type],
        "user_id": user_id,
        "user_query": user_query,
        "domain": domain,
        "domain_state": domain_state or {},
        "memory_store": memory_store,
        "global_context": global_context or {},
        "expected_action": expected_action,
        "expected_sql_pool": expected_sql_pool,
        "expected_applicability": expected_applicability,
        "expected_presented_constraints": expected_presented_constraints or [],
        "rationale": rationale,
        "code_path": CODE_PATH,
        "metric": METRICS,
    }


def _suffix(split: str, index: int) -> str:
    return f"{split[:3]}_{index:02d}"


# --- Group A: scope isolation ---


def _scope_same_user(split: str, index: int) -> dict[str, Any]:
    uid = f"user-a-{_suffix(split, index)}"
    prefix = f"scope_same_{_suffix(split, index)}"
    store = [
        _mem(f"{prefix}-h1", user_id=uid, text="ngân sách 1-2 triệu", domain="hotel"),
        _mem(f"{prefix}-h2", user_id=uid, text="ưu tiên yên tĩnh", domain="hotel"),
        _mem(f"{prefix}-h3", user_id=uid, text="thích boutique", domain="hotel"),
        _mem(f"{prefix}-h4", user_id=uid, text="gần trung tâm", domain="hotel"),
    ]
    pool = [m["memory_id"] for m in store]
    # Tool-field rubric on search_hotels: budget→apply; quiet/boutique/location soft→uncertain.
    expected_applicability = {
        f"{prefix}-h1": "apply",
        f"{prefix}-h2": "uncertain",
        f"{prefix}-h3": "uncertain",
        f"{prefix}-h4": "uncertain",
    }
    return _case(
        case_id=f"scope_same_user_same_domain_{_suffix(split, index)}",
        split=split,
        scenario_type="scope_same_user_same_domain",
        user_id=uid,
        user_query="Tìm khách sạn Hà Nội",
        domain="hotel",
        memory_store=store,
        expected_sql_pool=pool,
        expected_applicability=expected_applicability,
        expected_action="search_hotels",
        rationale="All active hotel memories for user must enter SQL pool.",
    )


def _scope_cross_user(split: str, index: int) -> dict[str, Any]:
    uid_a = f"user-a-{_suffix(split, index)}"
    uid_b = f"user-b-{_suffix(split, index)}"
    prefix = f"scope_xuser_{_suffix(split, index)}"
    store = [
        _mem(f"{prefix}-a1", user_id=uid_a, text="ngân sách 1-2 triệu", domain="hotel"),
        _mem(
            f"{prefix}-b1",
            user_id=uid_b,
            text="ngân sách 1-2 triệu",
            domain="hotel",
        ),
    ]
    return _case(
        case_id=f"scope_cross_user_{_suffix(split, index)}",
        split=split,
        scenario_type="scope_cross_user",
        user_id=uid_a,
        user_query="Tìm khách sạn ngân sách 1-2 triệu",
        domain="hotel",
        memory_store=store,
        expected_sql_pool=[f"{prefix}-a1"],
        expected_applicability={f"{prefix}-a1": "apply"},
        expected_action="search_hotels",
        rationale="User B memories must never enter user A SQL pool.",
    )


def _scope_cross_domain(split: str, index: int) -> dict[str, Any]:
    uid = f"user-a-{_suffix(split, index)}"
    prefix = f"scope_xdom_{_suffix(split, index)}"
    domains = [("hotel", "h"), ("flight", "f"), ("car", "c"), ("excursion", "e")]
    target_domain, short = domains[index % len(domains)]
    store = [
        _mem(f"{prefix}-h", user_id=uid, text="thích yên tĩnh", domain="hotel"),
        _mem(f"{prefix}-f", user_id=uid, text="ưu tiên bay thẳng", domain="flight"),
        _mem(f"{prefix}-c", user_id=uid, text="thích xe tự động", domain="car"),
        _mem(f"{prefix}-e", user_id=uid, text="thích tour văn hóa", domain="excursion"),
    ]
    pool_id = f"{prefix}-{short}"
    queries = {
        "hotel": "Tìm khách sạn Hà Nội",
        "flight": "Tìm chuyến bay tối",
        "car": "Thuê xe số tự động",
        "excursion": "Tìm tour tham quan",
    }
    actions = {
        "hotel": "search_hotels",
        "flight": "search_one_way",
        "car": "search_cars",
        "excursion": "search_attractions",
    }
    # Hotel quiet has no search_hotels tool field → uncertain; other domains stay apply.
    label = "uncertain" if target_domain == "hotel" else "apply"
    return _case(
        case_id=f"scope_cross_domain_{_suffix(split, index)}",
        split=split,
        scenario_type="scope_cross_domain",
        user_id=uid,
        user_query=queries[target_domain],
        domain=target_domain,
        memory_store=store,
        expected_sql_pool=[pool_id],
        expected_applicability={pool_id: label},
        expected_action=actions[target_domain],
        rationale="Cross-domain memories must not leak into domain SQL pool.",
    )


def _scope_inactive(split: str, index: int) -> dict[str, Any]:
    uid = f"user-a-{_suffix(split, index)}"
    prefix = f"scope_inact_{_suffix(split, index)}"
    store = [
        _mem(f"{prefix}-active", user_id=uid, text="ngân sách 1-2 triệu", domain="hotel"),
        _mem(
            f"{prefix}-old",
            user_id=uid,
            text="thích resort biển",
            domain="hotel",
            status="superseded",
        ),
    ]
    active_id = f"{prefix}-active"
    return _case(
        case_id=f"scope_inactive_{_suffix(split, index)}",
        split=split,
        scenario_type="scope_inactive",
        user_id=uid,
        user_query="Tìm khách sạn Hà Nội",
        domain="hotel",
        memory_store=store,
        expected_sql_pool=[active_id],
        expected_applicability={active_id: "apply"},
        expected_action="search_hotels",
        rationale="Inactive/superseded memories must not enter SQL pool.",
    )


def _scope_global_not_in_pool(split: str, index: int) -> dict[str, Any]:
    uid = f"user-a-{_suffix(split, index)}"
    prefix = f"scope_global_{_suffix(split, index)}"
    hotel_id = f"{prefix}-h1"
    profile_id = f"{prefix}-profile"
    store = [
        _mem(hotel_id, user_id=uid, text="ngân sách 1-2 triệu", domain="hotel"),
        _mem(
            profile_id,
            user_id=uid,
            text="anh Khoa",
            domain="general",
            category="profile_fact",
        ),
    ]
    return _case(
        case_id=f"scope_global_not_in_pool_{_suffix(split, index)}",
        split=split,
        scenario_type="scope_global_not_in_pool",
        user_id=uid,
        user_query="Tìm khách sạn Hà Nội",
        domain="hotel",
        memory_store=store,
        global_context={"memory_ids": [profile_id]},
        expected_sql_pool=[hotel_id],
        expected_applicability={hotel_id: "apply"},
        expected_action="search_hotels",
        rationale="Profile/global facts are not in domain travel_preferences SQL pool.",
    )


def _scope_empty_pool(split: str, index: int) -> dict[str, Any]:
    uid = f"user-empty-{_suffix(split, index)}"
    prefix = f"scope_empty_{_suffix(split, index)}"
    store = [
        _mem(f"{prefix}-f", user_id=uid, text="ưu tiên bay thẳng", domain="flight"),
    ]
    return _case(
        case_id=f"scope_empty_pool_{_suffix(split, index)}",
        split=split,
        scenario_type="scope_empty_pool",
        user_id=uid,
        user_query="Tìm khách sạn Hà Nội",
        domain="hotel",
        memory_store=store,
        expected_sql_pool=[],
        expected_applicability={},
        expected_action="search_hotels",
        rationale="Empty domain pool must not error; judge receives no candidates.",
    )


SCOPE_BUILDERS: dict[str, Callable[[str, int], dict[str, Any]]] = {
    "scope_same_user_same_domain": _scope_same_user,
    "scope_cross_user": _scope_cross_user,
    "scope_cross_domain": _scope_cross_domain,
    "scope_inactive": _scope_inactive,
    "scope_global_not_in_pool": _scope_global_not_in_pool,
    "scope_empty_pool": _scope_empty_pool,
}


# --- Group B: action contrast (hotel bathtub memory) ---


def _bathtub_store(uid: str, prefix: str) -> list[dict[str, Any]]:
    return [
        _mem(
            f"{prefix}-bathtub",
            user_id=uid,
            text="ưu tiên phòng có bồn tắm",
            domain="hotel",
        ),
        _mem(f"{prefix}-budget", user_id=uid, text="ngân sách 1-2 triệu", domain="hotel"),
    ]


def _action_hotel_search(split: str, index: int) -> dict[str, Any]:
    uid = f"user-a-{_suffix(split, index)}"
    prefix = f"act_h_search_{_suffix(split, index)}"
    store = _bathtub_store(uid, prefix)
    bathtub_id = f"{prefix}-bathtub"
    budget_id = f"{prefix}-budget"
    return _case(
        case_id=f"action_contrast_hotel_search_{_suffix(split, index)}",
        split=split,
        scenario_type="action_contrast_hotel_search",
        user_id=uid,
        user_query="Tìm khách sạn Hà Nội cho chuyến công tác",
        domain="hotel",
        memory_store=store,
        expected_sql_pool=[bathtub_id, budget_id],
        expected_applicability={bathtub_id: "irrelevant", budget_id: "apply"},
        expected_action="search_hotels",
        expected_presented_constraints=[
            {"memory_id": budget_id, "constraint": "budget=1-2m", "strength": "soft_preference"}
        ],
        rationale="Bathtub amenity irrelevant at search_hotels action.",
    )


def _action_hotel_details(split: str, index: int) -> dict[str, Any]:
    uid = f"user-a-{_suffix(split, index)}"
    prefix = f"act_h_det_{_suffix(split, index)}"
    store = _bathtub_store(uid, prefix)
    bathtub_id = f"{prefix}-bathtub"
    budget_id = f"{prefix}-budget"
    return _case(
        case_id=f"action_contrast_hotel_details_{_suffix(split, index)}",
        split=split,
        scenario_type="action_contrast_hotel_details",
        user_id=uid,
        user_query="Cho tôi xem các loại phòng của khách sạn này",
        domain="hotel",
        domain_state={"selected_hotel_id": "hotel_123"},
        memory_store=store,
        expected_sql_pool=[bathtub_id, budget_id],
        expected_applicability={bathtub_id: "uncertain", budget_id: "apply"},
        expected_action="get_hotel_details",
        expected_presented_constraints=[
            {"memory_id": bathtub_id, "constraint": "prefer_bathtub", "strength": "soft_preference"},
            {"memory_id": budget_id, "constraint": "budget=1-2m", "strength": "soft_preference"},
        ],
        rationale="Bathtub may be soft-priority at get_hotel_details.",
    )


def _action_hotel_select_room(split: str, index: int) -> dict[str, Any]:
    uid = f"user-a-{_suffix(split, index)}"
    prefix = f"act_h_sel_{_suffix(split, index)}"
    store = _bathtub_store(uid, prefix)
    bathtub_id = f"{prefix}-bathtub"
    budget_id = f"{prefix}-budget"
    return _case(
        case_id=f"action_contrast_hotel_select_room_{_suffix(split, index)}",
        split=split,
        scenario_type="action_contrast_hotel_select_room",
        user_id=uid,
        user_query="Chọn phòng cho hai người nghỉ dưỡng cuối tuần",
        domain="hotel",
        domain_state={"selected_hotel_id": "hotel_123", "guests": 2},
        memory_store=store,
        expected_sql_pool=[bathtub_id, budget_id],
        expected_applicability={bathtub_id: "apply", budget_id: "apply"},
        expected_action="select_room",
        expected_presented_constraints=[
            {"memory_id": bathtub_id, "constraint": "prefer_bathtub", "strength": "hard_preference"},
        ],
        rationale="Bathtub directly applies to select_room.",
    )


def _action_hotel_reviews(split: str, index: int) -> dict[str, Any]:
    uid = f"user-a-{_suffix(split, index)}"
    prefix = f"act_h_rev_{_suffix(split, index)}"
    store = _bathtub_store(uid, prefix)
    bathtub_id = f"{prefix}-bathtub"
    budget_id = f"{prefix}-budget"
    return _case(
        case_id=f"action_contrast_hotel_reviews_{_suffix(split, index)}",
        split=split,
        scenario_type="action_contrast_hotel_reviews",
        user_id=uid,
        user_query="Đánh giá review khách sạn này",
        domain="hotel",
        domain_state={"selected_hotel_id": "hotel_123"},
        memory_store=store,
        expected_sql_pool=[bathtub_id, budget_id],
        expected_applicability={bathtub_id: "irrelevant", budget_id: "irrelevant"},
        expected_action="get_reviews",
        rationale="Room features irrelevant at get_reviews.",
    )


def _action_flight_search(split: str, index: int) -> dict[str, Any]:
    uid = f"user-a-{_suffix(split, index)}"
    prefix = f"act_f_search_{_suffix(split, index)}"
    direct_id = f"{prefix}-direct"
    seat_id = f"{prefix}-seat"
    store = [
        _mem(direct_id, user_id=uid, text="ưu tiên bay thẳng", domain="flight"),
        _mem(seat_id, user_id=uid, text="muốn ghế cửa sổ", domain="flight"),
    ]
    return _case(
        case_id=f"action_contrast_flight_search_{_suffix(split, index)}",
        split=split,
        scenario_type="action_contrast_flight_search",
        user_id=uid,
        user_query="Tìm chuyến bay SGN đi Hà Nội",
        domain="flight",
        memory_store=store,
        expected_sql_pool=[direct_id, seat_id],
        expected_applicability={direct_id: "apply", seat_id: "irrelevant"},
        expected_action="search_one_way",
        expected_presented_constraints=[
            {"memory_id": direct_id, "constraint": "prefer_nonstop", "strength": "soft_preference"},
        ],
        rationale="Seat preference irrelevant before flight search.",
    )


def _action_flight_compare(split: str, index: int) -> dict[str, Any]:
    uid = f"user-a-{_suffix(split, index)}"
    prefix = f"act_f_cmp_{_suffix(split, index)}"
    direct_id = f"{prefix}-direct"
    seat_id = f"{prefix}-seat"
    store = [
        _mem(direct_id, user_id=uid, text="ưu tiên bay thẳng", domain="flight"),
        _mem(seat_id, user_id=uid, text="muốn ghế cửa sổ", domain="flight"),
    ]
    return _case(
        case_id=f"action_contrast_flight_compare_{_suffix(split, index)}",
        split=split,
        scenario_type="action_contrast_flight_compare",
        user_id=uid,
        user_query="So sánh các chuyến bay SGN-HAN",
        domain="flight",
        memory_store=store,
        expected_sql_pool=[direct_id, seat_id],
        expected_applicability={direct_id: "apply", seat_id: "uncertain"},
        expected_action="compare_offers",
        expected_presented_constraints=[
            {"memory_id": direct_id, "constraint": "prefer_nonstop", "strength": "soft_preference"},
            {"memory_id": seat_id, "constraint": "prefer_window_seat", "strength": "soft_preference"},
        ],
        rationale="Both may inform compare_offers ranking.",
    )


def _action_car_search(split: str, index: int) -> dict[str, Any]:
    uid = f"user-a-{_suffix(split, index)}"
    prefix = f"act_c_search_{_suffix(split, index)}"
    auto_id = f"{prefix}-auto"
    seven_id = f"{prefix}-7seat"
    store = [
        _mem(auto_id, user_id=uid, text="thích xe số tự động", domain="car"),
        _mem(seven_id, user_id=uid, text="thích xe 7 chỗ", domain="car"),
    ]
    return _case(
        case_id=f"action_contrast_car_search_{_suffix(split, index)}",
        split=split,
        scenario_type="action_contrast_car_search",
        user_id=uid,
        user_query="Thuê xe số tự động ở Đà Nẵng",
        domain="car",
        memory_store=store,
        expected_sql_pool=[auto_id, seven_id],
        expected_applicability={auto_id: "apply", seven_id: "apply"},
        expected_action="search_cars",
        rationale="Both transmission and 7-seat capacity map via user_needs on search_cars.",
    )


def _action_car_select(split: str, index: int) -> dict[str, Any]:
    uid = f"user-a-{_suffix(split, index)}"
    prefix = f"act_c_sel_{_suffix(split, index)}"
    auto_id = f"{prefix}-auto"
    seven_id = f"{prefix}-7seat"
    store = [
        _mem(auto_id, user_id=uid, text="thích xe số tự động", domain="car"),
        _mem(seven_id, user_id=uid, text="thích xe 7 chỗ", domain="car"),
    ]
    return _case(
        case_id=f"action_contrast_car_select_{_suffix(split, index)}",
        split=split,
        scenario_type="action_contrast_car_select",
        user_id=uid,
        user_query="Chọn xe phù hợp cho gia đình 6 người",
        domain="car",
        domain_state={"visible_results": {"r1": {"domain": "car", "search_id": "s1"}}},
        memory_store=store,
        expected_sql_pool=[auto_id, seven_id],
        expected_applicability={auto_id: "uncertain", seven_id: "apply"},
        expected_action="select_car",
        rationale="7-seat applies at select_car for family of 6.",
    )


def _action_excursion_search(split: str, index: int) -> dict[str, Any]:
    uid = f"user-a-{_suffix(split, index)}"
    prefix = f"act_e_search_{_suffix(split, index)}"
    culture_id = f"{prefix}-culture"
    beach_id = f"{prefix}-beach"
    store = [
        _mem(culture_id, user_id=uid, text="thích tour văn hóa", domain="excursion"),
        _mem(beach_id, user_id=uid, text="thích tour biển", domain="excursion"),
    ]
    return _case(
        case_id=f"action_contrast_excursion_search_{_suffix(split, index)}",
        split=split,
        scenario_type="action_contrast_excursion_search",
        user_id=uid,
        user_query="Tìm tour tham quan Đà Nẵng",
        domain="excursion",
        memory_store=store,
        expected_sql_pool=[culture_id, beach_id],
        expected_applicability={culture_id: "apply", beach_id: "uncertain"},
        expected_action="search_attractions",
        rationale="Culture tour preference applies at search.",
    )


def _action_excursion_details(split: str, index: int) -> dict[str, Any]:
    uid = f"user-a-{_suffix(split, index)}"
    prefix = f"act_e_det_{_suffix(split, index)}"
    culture_id = f"{prefix}-culture"
    beach_id = f"{prefix}-beach"
    store = [
        _mem(culture_id, user_id=uid, text="thích tour văn hóa", domain="excursion"),
        _mem(beach_id, user_id=uid, text="thích tour biển", domain="excursion"),
    ]
    return _case(
        case_id=f"action_contrast_excursion_details_{_suffix(split, index)}",
        split=split,
        scenario_type="action_contrast_excursion_details",
        user_id=uid,
        user_query="Xem chi tiết tour này",
        domain="excursion",
        domain_state={"selected_tour_id": "tour_42"},
        memory_store=store,
        expected_sql_pool=[culture_id, beach_id],
        expected_applicability={culture_id: "uncertain", beach_id: "irrelevant"},
        expected_action="get_details",
        rationale="Generic tour prefs uncertain at get_details.",
    )


ACTION_BUILDERS: dict[str, Callable[[str, int], dict[str, Any]]] = {
    "action_contrast_hotel_search": _action_hotel_search,
    "action_contrast_hotel_details": _action_hotel_details,
    "action_contrast_hotel_select_room": _action_hotel_select_room,
    "action_contrast_hotel_reviews": _action_hotel_reviews,
    "action_contrast_flight_search": _action_flight_search,
    "action_contrast_flight_compare": _action_flight_compare,
    "action_contrast_car_search": _action_car_search,
    "action_contrast_car_select": _action_car_select,
    "action_contrast_excursion_search": _action_excursion_search,
    "action_contrast_excursion_details": _action_excursion_details,
}


# --- Group C: overrides ---


def _override_flight_time(split: str, index: int) -> dict[str, Any]:
    uid = f"user-a-{_suffix(split, index)}"
    prefix = f"ovr_f_time_{_suffix(split, index)}"
    morning_id = f"{prefix}-morning"
    direct_id = f"{prefix}-direct"
    store = [
        _mem(morning_id, user_id=uid, text="ưu tiên bay sáng", domain="flight"),
        _mem(direct_id, user_id=uid, text="ưu tiên bay thẳng", domain="flight"),
    ]
    return _case(
        case_id=f"override_flight_time_{_suffix(split, index)}",
        split=split,
        scenario_type="override_flight_time",
        user_id=uid,
        user_query="Hôm nay tìm chuyến bay tối, sáng tôi bận",
        domain="flight",
        memory_store=store,
        expected_sql_pool=[morning_id, direct_id],
        expected_applicability={morning_id: "overridden", direct_id: "apply"},
        expected_action="search_one_way",
        expected_presented_constraints=[
            {"memory_id": direct_id, "constraint": "prefer_nonstop", "strength": "soft_preference"},
        ],
        rationale="Morning preference overridden by evening request.",
    )


def _override_hotel_budget(split: str, index: int) -> dict[str, Any]:
    uid = f"user-a-{_suffix(split, index)}"
    prefix = f"ovr_h_budget_{_suffix(split, index)}"
    old_id = f"{prefix}-old"
    quiet_id = f"{prefix}-quiet"
    store = [
        _mem(old_id, user_id=uid, text="ngân sách 1-2 triệu", domain="hotel"),
        _mem(quiet_id, user_id=uid, text="ưu tiên yên tĩnh", domain="hotel"),
    ]
    queries = [
        "Lần này tối đa 5 triệu mỗi đêm, tìm khách sạn Hà Nội",
        "Tìm khách sạn Hà Nội, budget tối đa 5 triệu đêm này",
        "Khách sạn Hà Nội, lần này tôi chi tối đa 5 triệu",
    ]
    return _case(
        case_id=f"override_hotel_budget_{_suffix(split, index)}",
        split=split,
        scenario_type="override_hotel_budget",
        user_id=uid,
        user_query=queries[index % len(queries)],
        domain="hotel",
        memory_store=store,
        expected_sql_pool=[old_id, quiet_id],
        expected_applicability={old_id: "overridden", quiet_id: "uncertain"},
        expected_action="search_hotels",
        rationale="Stored budget overridden by explicit higher cap; quiet has no tool field.",
    )


def _override_hotel_location_uncertain(split: str, index: int) -> dict[str, Any]:
    uid = f"user-a-{_suffix(split, index)}"
    prefix = f"ovr_h_loc_{_suffix(split, index)}"
    beach_id = f"{prefix}-beach"
    budget_id = f"{prefix}-budget"
    store = [
        _mem(beach_id, user_id=uid, text="thích gần biển", domain="hotel"),
        _mem(budget_id, user_id=uid, text="ngân sách 1-2 triệu", domain="hotel"),
    ]
    return _case(
        case_id=f"override_hotel_location_uncertain_{_suffix(split, index)}",
        split=split,
        scenario_type="override_hotel_location_uncertain",
        user_id=uid,
        user_query="Tìm hotel trung tâm Hà Nội cho chuyến công tác",
        domain="hotel",
        memory_store=store,
        expected_sql_pool=[beach_id, budget_id],
        expected_applicability={beach_id: "uncertain", budget_id: "apply"},
        expected_action="search_hotels",
        rationale="Beach preference has no search_hotels tool field → uncertain (not irrelevant).",
    )


def _override_car_transmission(split: str, index: int) -> dict[str, Any]:
    uid = f"user-a-{_suffix(split, index)}"
    prefix = f"ovr_c_trans_{_suffix(split, index)}"
    auto_id = f"{prefix}-auto"
    wide_id = f"{prefix}-wide"
    store = [
        _mem(auto_id, user_id=uid, text="thích xe số tự động", domain="car"),
        _mem(wide_id, user_id=uid, text="ưu tiên xe rộng rãi", domain="car"),
    ]
    return _case(
        case_id=f"override_car_transmission_{_suffix(split, index)}",
        split=split,
        scenario_type="override_car_transmission",
        user_id=uid,
        user_query="Tôi chỉ lái được xe số sàn lần này, thuê xe Đà Nẵng",
        domain="car",
        memory_store=store,
        expected_sql_pool=[auto_id, wide_id],
        expected_applicability={auto_id: "overridden", wide_id: "apply"},
        expected_action="search_cars",
        rationale="Automatic preference overridden by manual-only request.",
    )


def _override_flight_departure(split: str, index: int) -> dict[str, Any]:
    uid = f"user-a-{_suffix(split, index)}"
    prefix = f"ovr_f_dep_{_suffix(split, index)}"
    sgn_id = f"{prefix}-sgn"
    direct_id = f"{prefix}-direct"
    store = [
        _mem(sgn_id, user_id=uid, text="thường bay từ SGN", domain="flight"),
        _mem(direct_id, user_id=uid, text="ưu tiên bay thẳng", domain="flight"),
    ]
    return _case(
        case_id=f"override_flight_departure_{_suffix(split, index)}",
        split=split,
        scenario_type="override_flight_departure",
        user_id=uid,
        user_query="Tôi đang ở Hà Nội, bay từ HAN đi Đà Nẵng",
        domain="flight",
        memory_store=store,
        expected_sql_pool=[sgn_id, direct_id],
        expected_applicability={sgn_id: "overridden", direct_id: "apply"},
        expected_action="search_one_way",
        expected_presented_constraints=[
            {"memory_id": direct_id, "constraint": "prefer_nonstop", "strength": "soft_preference"},
        ],
        rationale="Home airport SGN overridden by current HAN departure.",
    )


OVERRIDE_BUILDERS: dict[str, Callable[[str, int], dict[str, Any]]] = {
    "override_flight_time": _override_flight_time,
    "override_hotel_budget": _override_hotel_budget,
    "override_hotel_location_uncertain": _override_hotel_location_uncertain,
    "override_car_transmission": _override_car_transmission,
    "override_flight_departure": _override_flight_departure,
}


# --- Group D: soft preferences ---


def _soft_hotel_quiet(split: str, index: int) -> dict[str, Any]:
    uid = f"user-a-{_suffix(split, index)}"
    prefix = f"soft_h_quiet_{_suffix(split, index)}"
    quiet_id = f"{prefix}-quiet"
    store = [_mem(quiet_id, user_id=uid, text="thích khách sạn yên tĩnh", domain="hotel")]
    return _case(
        case_id=f"soft_hotel_quiet_uncertain_{_suffix(split, index)}",
        split=split,
        scenario_type="soft_hotel_quiet_uncertain",
        user_id=uid,
        user_query="Tìm hotel công tác Hà Nội",
        domain="hotel",
        memory_store=store,
        expected_sql_pool=[quiet_id],
        expected_applicability={quiet_id: "uncertain"},
        expected_action="search_hotels",
        expected_presented_constraints=[
            {"memory_id": quiet_id, "constraint": "prefer_quiet", "strength": "soft_preference"},
        ],
        rationale="Quiet preference has no search_hotels tool field → uncertain soft preference.",
    )


def _soft_hotel_avoid_groups(split: str, index: int) -> dict[str, Any]:
    uid = f"user-a-{_suffix(split, index)}"
    prefix = f"soft_h_grp_{_suffix(split, index)}"
    group_id = f"{prefix}-group"
    store = [_mem(group_id, user_id=uid, text="tránh khách đoàn", domain="hotel")]
    return _case(
        case_id=f"soft_hotel_avoid_groups_uncertain_{_suffix(split, index)}",
        split=split,
        scenario_type="soft_hotel_avoid_groups_uncertain",
        user_id=uid,
        user_query="Tìm hotel cuối tuần Đà Nẵng",
        domain="hotel",
        memory_store=store,
        expected_sql_pool=[group_id],
        expected_applicability={group_id: "uncertain"},
        expected_action="search_hotels",
        expected_presented_constraints=[
            {"memory_id": group_id, "constraint": "avoid_groups", "strength": "soft_preference"},
        ],
        rationale="Avoid groups is uncertain soft priority, not hard filter.",
    )


def _soft_hotel_bathtub(split: str, index: int) -> dict[str, Any]:
    uid = f"user-a-{_suffix(split, index)}"
    prefix = f"soft_h_bath_{_suffix(split, index)}"
    bath_id = f"{prefix}-bath"
    store = [_mem(bath_id, user_id=uid, text="thích bồn tắm", domain="hotel")]
    return _case(
        case_id=f"soft_hotel_bathtub_uncertain_{_suffix(split, index)}",
        split=split,
        scenario_type="soft_hotel_bathtub_uncertain",
        user_id=uid,
        user_query="Tìm hotel nghỉ dưỡng cuối tuần",
        domain="hotel",
        memory_store=store,
        expected_sql_pool=[bath_id],
        expected_applicability={bath_id: "uncertain"},
        expected_action="search_hotels",
        expected_presented_constraints=[
            {"memory_id": bath_id, "constraint": "prefer_bathtub", "strength": "soft_preference"},
        ],
        rationale="Bathtub uncertain at search without room-level data.",
    )


def _soft_flight_direct(split: str, index: int) -> dict[str, Any]:
    uid = f"user-a-{_suffix(split, index)}"
    prefix = f"soft_f_dir_{_suffix(split, index)}"
    direct_id = f"{prefix}-direct"
    store = [_mem(direct_id, user_id=uid, text="ưu tiên bay thẳng", domain="flight")]
    return _case(
        case_id=f"soft_flight_direct_apply_{_suffix(split, index)}",
        split=split,
        scenario_type="soft_flight_direct_apply",
        user_id=uid,
        user_query="Tìm vé SGN đi Hà Nội",
        domain="flight",
        memory_store=store,
        expected_sql_pool=[direct_id],
        expected_applicability={direct_id: "apply"},
        expected_action="search_one_way",
        expected_presented_constraints=[
            {"memory_id": direct_id, "constraint": "prefer_nonstop", "strength": "soft_preference"},
        ],
        rationale="Direct flight preference applies at search.",
    )


def _soft_flight_lowest_price(split: str, index: int) -> dict[str, Any]:
    uid = f"user-a-{_suffix(split, index)}"
    prefix = f"soft_f_cheap_{_suffix(split, index)}"
    cheap_id = f"{prefix}-cheap"
    store = [_mem(cheap_id, user_id=uid, text="thường chọn rẻ nhất", domain="flight")]
    queries = [
        "Tìm chuyến bay đúng giờ nhất SGN-HAN",
        "Tìm chuyến bay khởi hành đúng giờ, không cần rẻ nhất",
    ]
    label = "uncertain" if index % 2 == 0 else "irrelevant"
    presented = (
        [{"memory_id": cheap_id, "constraint": "prefer_cheapest", "strength": "soft_preference"}]
        if label == "uncertain"
        else []
    )
    return _case(
        case_id=f"soft_flight_lowest_price_uncertain_{_suffix(split, index)}",
        split=split,
        scenario_type="soft_flight_lowest_price_uncertain",
        user_id=uid,
        user_query=queries[index % len(queries)],
        domain="flight",
        memory_store=store,
        expected_sql_pool=[cheap_id],
        expected_applicability={cheap_id: label},
        expected_action="search_one_way",
        expected_presented_constraints=presented,
        rationale="Cheapest pref uncertain/irrelevant when user prioritizes schedule.",
    )


SOFT_BUILDERS: dict[str, Callable[[str, int], dict[str, Any]]] = {
    "soft_hotel_quiet_uncertain": _soft_hotel_quiet,
    "soft_hotel_avoid_groups_uncertain": _soft_hotel_avoid_groups,
    "soft_hotel_bathtub_uncertain": _soft_hotel_bathtub,
    "soft_flight_direct_apply": _soft_flight_direct,
    "soft_flight_lowest_price_uncertain": _soft_flight_lowest_price,
}


# --- Group E: domain state ---


def _state_hotel_bathtub_apply(split: str, index: int) -> dict[str, Any]:
    uid = f"user-a-{_suffix(split, index)}"
    prefix = f"state_h_bath_y_{_suffix(split, index)}"
    bath_id = f"{prefix}-bath"
    store = [_mem(bath_id, user_id=uid, text="người dùng thích phòng có bồn tắm", domain="hotel")]
    return _case(
        case_id=f"state_hotel_bathtub_apply_with_selection_{_suffix(split, index)}",
        split=split,
        scenario_type="state_hotel_bathtub_apply_with_selection",
        user_id=uid,
        user_query="Chọn giúp tôi phòng phù hợp nhất",
        domain="hotel",
        domain_state={
            "selected_hotel_id": "hotel_123",
            "guests": 2,
            "trip_purpose": "leisure",
        },
        memory_store=store,
        expected_sql_pool=[bath_id],
        expected_applicability={bath_id: "apply"},
        expected_action="select_room",
        expected_presented_constraints=[
            {"memory_id": bath_id, "constraint": "prefer_bathtub", "strength": "hard_preference"},
        ],
        rationale="Bathtub applies when hotel selected and selecting room.",
    )


def _state_hotel_bathtub_irrelevant(split: str, index: int) -> dict[str, Any]:
    uid = f"user-a-{_suffix(split, index)}"
    prefix = f"state_h_bath_n_{_suffix(split, index)}"
    bath_id = f"{prefix}-bath"
    store = [_mem(bath_id, user_id=uid, text="người dùng thích phòng có bồn tắm", domain="hotel")]
    return _case(
        case_id=f"state_hotel_bathtub_irrelevant_without_selection_{_suffix(split, index)}",
        split=split,
        scenario_type="state_hotel_bathtub_irrelevant_without_selection",
        user_id=uid,
        user_query="Tìm khách sạn cho tôi",
        domain="hotel",
        domain_state={"destination": None},
        memory_store=store,
        expected_sql_pool=[bath_id],
        expected_applicability={bath_id: "irrelevant"},
        expected_action="search_hotels",
        rationale="Bathtub irrelevant at hotel search without selection context.",
    )


def _state_flight_seat(split: str, index: int) -> dict[str, Any]:
    uid = f"user-a-{_suffix(split, index)}"
    prefix = f"state_f_seat_{_suffix(split, index)}"
    seat_id = f"{prefix}-seat"
    store = [_mem(seat_id, user_id=uid, text="muốn ghế cửa sổ", domain="flight")]
    return _case(
        case_id=f"state_flight_seat_with_shortlist_{_suffix(split, index)}",
        split=split,
        scenario_type="state_flight_seat_with_shortlist",
        user_id=uid,
        user_query="Chọn chuyến bay phù hợp nhất trong danh sách",
        domain="flight",
        domain_state={
            "visible_results": {
                "r1": {"domain": "flight", "search_id": "s1", "displayed_item_ids": ["f1", "f2"]}
            }
        },
        memory_store=store,
        expected_sql_pool=[seat_id],
        expected_applicability={seat_id: "apply"},
        expected_action="compare_offers",
        expected_presented_constraints=[
            {"memory_id": seat_id, "constraint": "prefer_window_seat", "strength": "soft_preference"},
        ],
        rationale="Seat preference applies when comparing shortlisted flights.",
    )


def _state_car_capacity(split: str, index: int) -> dict[str, Any]:
    uid = f"user-a-{_suffix(split, index)}"
    prefix = f"state_c_cap_{_suffix(split, index)}"
    seven_id = f"{prefix}-7seat"
    store = [_mem(seven_id, user_id=uid, text="thích xe 7 chỗ", domain="car")]
    return _case(
        case_id=f"state_car_capacity_with_trip_context_{_suffix(split, index)}",
        split=split,
        scenario_type="state_car_capacity_with_trip_context",
        user_id=uid,
        user_query="Thuê xe cho chuyến đi gia đình",
        domain="car",
        domain_state={"passengers": 6, "trip_purpose": "family"},
        memory_store=store,
        expected_sql_pool=[seven_id],
        expected_applicability={seven_id: "apply"},
        expected_action="search_cars",
        expected_presented_constraints=[
            {"memory_id": seven_id, "constraint": "prefer_7_seats", "strength": "soft_preference"},
        ],
        rationale="7-seat preference applies with family trip context.",
    )


STATE_BUILDERS: dict[str, Callable[[str, int], dict[str, Any]]] = {
    "state_hotel_bathtub_apply_with_selection": _state_hotel_bathtub_apply,
    "state_hotel_bathtub_irrelevant_without_selection": _state_hotel_bathtub_irrelevant,
    "state_flight_seat_with_shortlist": _state_flight_seat,
    "state_car_capacity_with_trip_context": _state_car_capacity,
}

ALL_BUILDERS: dict[str, Callable[[str, int], dict[str, Any]]] = {
    **SCOPE_BUILDERS,
    **ACTION_BUILDERS,
    **OVERRIDE_BUILDERS,
    **SOFT_BUILDERS,
    **STATE_BUILDERS,
}


def build_all_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for scenario_type in SCENARIO_TYPES:
        dev_count, test_count = SPLIT_COUNTS[scenario_type]
        builder = ALL_BUILDERS[scenario_type]
        for index in range(dev_count):
            cases.append(builder("development", index))
        for index in range(test_count):
            cases.append(builder("test", index))
    return cases


def main() -> None:
    cases = build_all_cases()
    errors = validate_dataset(cases)
    if errors:
        raise ValueError("dataset validation failed:\n" + "\n".join(errors))

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    jsonl_path = FIXTURE_DIR / "retrieval_cases.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(case, ensure_ascii=False) + "\n")

    manifest = build_manifest(cases)
    manifest_path = FIXTURE_DIR / "retrieval_split_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(cases)} cases to {jsonl_path}")
    print(f"Wrote manifest to {manifest_path}")


if __name__ == "__main__":
    main()
