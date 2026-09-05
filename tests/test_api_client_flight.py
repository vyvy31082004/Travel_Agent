"""Unit tests for flight API helpers."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from utils.api_client_flight import (  # noqa: E402
    _clean_request_params,
    _filter_flight_constraints,
    _outbound_only_pair,
    _pair_one_way_legs,
    search_one_way_flights_from_api,
    search_roundtrip_flights_from_api,
)


def test_clean_request_params_serializes_dates():
    params = {
        "departureDate": date(2026, 9, 5),
        "adults": "2",
        "empty": None,
    }
    cleaned = _clean_request_params(params)
    assert cleaned["departureDate"] == "2026-09-05"
    assert cleaned["adults"] == "2"
    assert "empty" not in cleaned


def test_outbound_only_pair_shape():
    pair = _outbound_only_pair({"price": 100, "airline_code": "VJ"}, warning="test")
    assert pair["Offer_ID"].startswith("FL-")
    assert pair["outbound"]["airline_code"] == "VJ"
    assert pair["inbound"] is None
    assert pair["warning"] == "test"


def test_pair_one_way_legs_merges_numeric_prices():
    pairs = _pair_one_way_legs(
        [{"price": "100", "airline_code": "VJ"}],
        [{"price": 200, "airline_code": "VN", "detailToken": "tok"}],
    )
    assert len(pairs) == 1
    assert pairs[0]["price"] == 300
    assert pairs[0]["outbound"]["airline_code"] == "VJ"
    assert pairs[0]["inbound"]["airline_code"] == "VN"


def test_pair_one_way_legs_skips_unparseable_prices():
    assert _pair_one_way_legs(
        [{"price": "unknown", "airline_code": "VJ"}],
        [{"price": 200, "airline_code": "VN"}],
    ) == []


def test_fetch_inbound_without_token_returns_list():
    result = [
        _outbound_only_pair(
            {"price": 100},
            warning="Không có returningToken; chỉ hiển thị chiều đi.",
        )
    ]
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["outbound"]["price"] == 100


@patch("utils.api_client_flight.search_flight_location_from_api")
@patch("utils.api_client_flight._booking_get")
def test_roundtrip_falls_back_to_one_way_when_empty(mock_booking_get, mock_location):
    mock_location.side_effect = lambda query: {
        "code": query.upper() if len(query) == 3 else "SGN",
        "id": query.upper() if len(query) == 3 else "SGN",
    }
    mock_booking_get.return_value = {"topFlights": [], "otherFlights": []}

    with patch("utils.api_client_flight.search_one_way_flights_from_api") as mock_one_way:
        mock_one_way.side_effect = [
            [{
                "topFlights": [{"price": 100, "airline_code": "VJ"}],
                "otherFlights": [],
            }],
            [{
                "topFlights": [{"price": 200, "airline_code": "VN"}],
                "otherFlights": [],
            }],
        ]
        result = search_roundtrip_flights_from_api(
            origin="SGN",
            destination="DAD",
            departure_date="05/09/2026",
            return_date="07/09/2026",
            adults=2,
        )

    assert result[0].get("fallback") == "one_way"
    assert len(result[0]["topFlights"]) >= 1


@patch("utils.api_client_flight.search_one_way_flights_from_api")
@patch("utils.api_client_flight.search_flight_location_from_api")
@patch("utils.api_client_flight._booking_get")
def test_roundtrip_fallback_forwards_leg_specific_time_constraints(
    mock_booking_get,
    mock_location,
    mock_one_way,
):
    mock_location.side_effect = lambda query: {"code": query}
    mock_booking_get.return_value = {"topFlights": [], "otherFlights": []}
    mock_one_way.side_effect = [
        [{"topFlights": [{"price": 100}], "otherFlights": []}],
        [{"topFlights": [{"price": 200}], "otherFlights": []}],
    ]

    search_roundtrip_flights_from_api(
        "SGN",
        "DAD",
        departure_date="2026-10-20",
        return_date="2026-10-23",
        preferred_departure_time="08:00",
        preferred_arrival_time="10:00",
        preferred_return_departure_time="18:00",
        preferred_return_arrival_time="20:00",
        time_tolerance_minutes=45,
    )

    outbound_call, inbound_call = mock_one_way.call_args_list
    assert outbound_call.kwargs["preferred_departure_time"] == "08:00"
    assert outbound_call.kwargs["preferred_arrival_time"] == "10:00"
    assert inbound_call.kwargs["preferred_departure_time"] == "18:00"
    assert inbound_call.kwargs["preferred_arrival_time"] == "20:00"
    assert outbound_call.kwargs["time_tolerance_minutes"] == 45
    assert inbound_call.kwargs["time_tolerance_minutes"] == 45


def test_filter_flight_constraints_applies_stops_airline_and_price():
    flights = [
        {"airline_code": "VN", "stops": 0, "price": 1_000_000},
        {"airline_code": "VJ", "stops": 0, "price": 900_000},
        {"airline_code": "VN", "stops": 1, "price": 800_000},
        {"airline_code": "VN", "stops": 0, "price": 2_000_000},
    ]

    assert _filter_flight_constraints(
        flights,
        stops="1",
        airlines="Vietnam Airlines",
        max_price=1_500_000,
    ) == [flights[0]]


@patch("utils.api_client_flight.search_flight_location_from_api")
@patch("utils.api_client_flight._booking_get")
def test_one_way_limits_total_results_and_filters_constraints(
    mock_booking_get,
    mock_location,
):
    mock_location.side_effect = lambda query: {"code": query}
    mock_booking_get.return_value = {
        "topFlights": [
            {
                "flights": [{
                    "departure_airport": {"airport_code": "SGN", "time": "2026-10-20 08:00"},
                    "arrival_airport": {"airport_code": "DAD", "time": "2026-10-20 09:20"},
                    "airline": "Vietnam Airlines",
                    "flight_number": "VN 100",
                }],
                "price": 1_000_000,
                "stops": 0,
            },
            {
                "flights": [{
                    "departure_airport": {"airport_code": "SGN", "time": "2026-10-20 10:00"},
                    "arrival_airport": {"airport_code": "DAD", "time": "2026-10-20 11:20"},
                    "airline": "VietJet",
                    "flight_number": "VJ 200",
                }],
                "price": 900_000,
                "stops": 0,
            },
        ],
        "otherFlights": [],
    }

    result = search_one_way_flights_from_api(
        "SGN",
        "DAD",
        departure_date="2026-10-20",
        stops="1",
        airlines="Vietnam Airlines",
        max_price=1_500_000,
        limit=1,
    )[0]

    assert len(result["topFlights"]) == 1
    assert result["topFlights"][0]["airline_code"] == "VN"
    assert result["otherFlights"] == []


@patch("utils.api_client_flight.search_flight_location_from_api")
@patch("utils.api_client_flight._booking_get")
def test_roundtrip_caps_next_flight_calls_and_output(
    mock_booking_get,
    mock_location,
):
    mock_location.side_effect = lambda query: {"code": query}

    def offer(number, token, price=1_000_000):
        return {
            "flights": [{
                "departure_airport": {"airport_code": "SGN", "time": "2026-10-20 08:00"},
                "arrival_airport": {"airport_code": "DAD", "time": "2026-10-20 09:20"},
                "airline": "Vietnam Airlines",
                "flight_number": number,
            }],
            "price": price,
            "stops": 0,
            "next_token": token,
            "booking_token": "book-" + token,
        }

    outbound = {
        "topFlights": [offer("VN 100", "next-1"), offer("VN 101", "next-2")],
        "otherFlights": [offer("VN 102", "next-3")],
    }
    inbound = {
        "topFlights": [offer("VN 200", "unused", 700_000)],
        "otherFlights": [offer("VN 201", "unused", 800_000)],
    }
    mock_booking_get.side_effect = [outbound, inbound]

    result = search_roundtrip_flights_from_api(
        "SGN",
        "DAD",
        departure_date="2026-10-20",
        return_date="2026-10-23",
        limit=1,
    )[0]

    assert mock_booking_get.call_count == 2
    assert len(result["topFlights"]) == 1
    assert result["otherFlights"] == []
    assert result["topFlights"][0]["outbound"]["departure_airport_code"] == "SGN"
    assert result["topFlights"][0]["price"] == 700_000


def test_unsupported_provider_constraint_returns_explicit_error():
    result = search_one_way_flights_from_api(
        "SGN",
        "DAD",
        departure_date="2026-10-20",
        carry_on_bag=1,
    )
    assert "chưa hỗ trợ" in result[0]["error"]
