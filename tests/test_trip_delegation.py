"""Tests for deterministic trip-plan delegation."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from agents.primary.trip_delegation import (  # noqa: E402
    build_domain_request,
    domain_turn_constraints,
    is_trip_plan_message,
    normalize_branch_args,
    normalize_branch_request,
    parse_trip_plan_fields,
    resolve_delegated_request,
)
from planner_smoke_lib import DEFAULT_PLANNER_MESSAGE  # noqa: E402


def test_is_trip_plan_message_detects_planner_prompt():
    assert is_trip_plan_message(DEFAULT_PLANNER_MESSAGE)


def test_parse_trip_plan_fields_from_smoke_message():
    fields = parse_trip_plan_fields(DEFAULT_PLANNER_MESSAGE)
    assert fields.origin_code == "SGN"
    assert fields.destination_code == "DAD"
    assert fields.destination and "đà nẵng" in fields.destination.lower()
    assert fields.adults == 2
    assert fields.departure_date
    assert fields.return_date
    assert fields.checkin_date == fields.departure_date
    assert fields.checkout_date == fields.return_date
    assert fields.duration_label == "3 ngày 2 đêm"
    assert any("yên tĩnh" in item.lower() for item in fields.constraints)


def test_build_domain_request_scopes_each_domain():
    fields = parse_trip_plan_fields(DEFAULT_PLANNER_MESSAGE)
    flight = build_domain_request("flight", fields)
    hotel = build_domain_request("hotel", fields)
    excursion = build_domain_request("excursion", fields)
    car = build_domain_request("car", fields)

    assert "khứ hồi" in flight.lower()
    assert "khách sạn" in hotel.lower()
    assert "tour" in excursion.lower() or "hoạt động" in excursion.lower()
    assert "thuê xe" in car.lower()
    assert "chuyến bay" not in hotel.lower()
    assert "chuyến bay" not in car.lower()


def test_normalize_branch_request_overrides_hotel_scope():
    user_message = DEFAULT_PLANNER_MESSAGE
    llm_request = user_message
    request, constraints = normalize_branch_request(
        "ToHotelAssistant",
        llm_request,
        user_message,
    )
    assert "khách sạn" in request.lower()
    assert "chuyến bay" not in request.lower()
    assert any("yên tĩnh" in item.lower() for item in constraints)


def test_domain_turn_constraints_only_for_hotel_and_excursion():
    fields = parse_trip_plan_fields(DEFAULT_PLANNER_MESSAGE)
    assert domain_turn_constraints("hotel", fields)
    assert domain_turn_constraints("excursion", fields)
    assert domain_turn_constraints("flight", fields) == []
    assert domain_turn_constraints("car", fields) == []


def test_branch_state_normalizes_trip_plan_delegation():
    from agents.primary.agent import _branch_state
    from langchain_core.messages import AIMessage, HumanMessage

    user_message = DEFAULT_PLANNER_MESSAGE
    state = {
        "messages": [
            HumanMessage(content=user_message),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "hotel-1",
                        "name": "ToHotelAssistant",
                        "args": {
                            "request": user_message,
                            "turn_constraints": [],
                        },
                    },
                ],
            ),
        ]
    }
    hotel_branch = _branch_state(
        state,
        state["messages"][-1].tool_calls[0],
    )
    assert "khách sạn" in hotel_branch["delegated_request"].lower()
    assert "chuyến bay" not in hotel_branch["delegated_request"].lower()
    assert any("yên tĩnh" in item.lower() for item in hotel_branch["turn_constraints"])


def test_normalize_by_assistant_node_when_tool_name_mismatches():
    msg = DEFAULT_PLANNER_MESSAGE
    args = normalize_branch_args(
        "WrongToolName",
        {"request": "Tim chuyen bay SGN-DAD", "turn_constraints": []},
        msg,
        assistant_node="hotel_assistant",
    )
    assert "khách sạn" in args["request"].lower()
    assert "chuyến bay" not in args["request"].lower()


def test_resolve_delegated_request_safety_net():
    request, _constraints = resolve_delegated_request(
        "car",
        "Tìm chuyến bay khứ hồi SGN-DAD",
        DEFAULT_PLANNER_MESSAGE,
        [],
    )
    assert "thuê xe" in request.lower()
    assert "chuyến bay" not in request.lower()


def test_normalize_branch_args_preserves_llm_constraints_when_not_trip_plan():
    args = normalize_branch_args(
        "ToHotelAssistant",
        {
            "request": "Tìm khách sạn Hà Nội",
            "turn_constraints": ["gần hồ Gươm"],
        },
        "Tìm khách sạn Hà Nội 2 đêm",
    )
    assert args["request"] == "Tìm khách sạn Hà Nội"
    assert args["turn_constraints"] == ["gần hồ Gươm"]


def test_parse_future_dates_from_dynamic_message():
    depart = (date.today() + timedelta(days=10)).strftime("%d/%m/%Y")
    ret = (date.today() + timedelta(days=12)).strftime("%d/%m/%Y")
    message = (
        f"Lên kế hoạch 3 ngày 2 đêm Đà Nẵng từ TP.HCM: "
        f"bay đi SGN→DAD ngày {depart}, bay về DAD→SGN ngày {ret}, "
        f"check-in {depart}, check-out {ret}, 2 người lớn."
    )
    fields = parse_trip_plan_fields(message)
    assert fields.departure_date == depart
    assert fields.return_date == ret
