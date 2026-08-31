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
    _outbound_only_pair,
    _pair_one_way_legs,
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


def test_pair_one_way_legs_merges_prices():
    pairs = _pair_one_way_legs(
        [{"price": 100, "airline_code": "VJ"}],
        [{"price": 200, "airline_code": "VN", "detailToken": "tok"}],
    )
    assert len(pairs) == 1
    assert pairs[0]["price"] == 300
    assert pairs[0]["outbound"]["airline_code"] == "VJ"
    assert pairs[0]["inbound"]["airline_code"] == "VN"


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
