"""Unit tests for flight API helpers."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from utils.api_client_flight import (  # noqa: E402
    FLIGHT_BOOKING_DETAILS_ENDPOINT,
    FLIGHT_BOOKING_URL_ENDPOINT,
    FLIGHT_NEXT_ENDPOINT,
    FLIGHT_SEARCH_ENDPOINT,
    _clean_request_params,
    _filter_flight_constraints,
    _map_cabin_class,
    _map_search_type,
    _normalize_flight_offer,
    _outbound_only_pair,
    _pair_one_way_legs,
    get_booking_link_from_api,
    remove_vietnamese_accents,
    search_flight_location_from_api,
    search_one_way_flights_from_api,
    search_roundtrip_flights_from_api,
)
from memory.normalize import normalize_flight_offers  # noqa: E402


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


def test_remove_vietnamese_accents_phu_yen():
    assert remove_vietnamese_accents("Phú Yên") == "Phu Yen"
    assert remove_vietnamese_accents("Đà Nẵng") == "Da Nang"


@patch("utils.api_client_flight._booking_get")
def test_search_flight_location_takes_data0_id(mock_booking_get):
    mock_booking_get.return_value = [
        {
            "id": "TBB",
            "type": "airport",
            "title": "Cảng Hàng không Tuy Hòa",
            "subtitle": "Sân bay ở Phú Yên, Việt Nam",
            "city": "Tuy Hòa",
            "distance": None,
            "list": None,
        },
        {
            "id": "/g/11z42h2d8z",
            "type": "other",
            "title": "Tuy Hòa",
            "subtitle": None,
            "city": "Tuy Hòa",
            "list": [
                {
                    "id": "TBB",
                    "type": "airport",
                    "title": "Cảng Hàng không Tuy Hòa",
                    "city": "Tuy Hòa",
                },
            ],
        },
        {
            "id": "/m/06n_yd",
            "type": "other",
            "title": "Tuy Hóa, Trung Quốc",
            "city": "Tuy Hóa",
            "list": [
                {"id": "HRB", "type": "airport", "title": "Harbin"},
                {"id": "DQA", "type": "airport", "title": "Daqing"},
            ],
        },
    ]

    result = search_flight_location_from_api("Phú Yên")

    mock_booking_get.assert_called_once()
    args, kwargs = mock_booking_get.call_args
    assert args[0] == "google_flight"
    assert args[1] == "/api/v1/searchAirport"
    assert args[2]["query"] == "Phu Yen"
    assert result["id"] == "TBB"
    assert result["code"] == "TBB"
    assert result["name"] == "Cảng Hàng không Tuy Hòa"
    assert result["city"] == "Tuy Hòa"
    assert result["source"] == "google_flights2_searchAirport"
    assert "error" not in result


def test_search_flight_location_iata_passthrough():
    result = search_flight_location_from_api("TBB")
    assert result["id"] == "TBB"
    assert result["code"] == "TBB"
    assert result["source"] == "iata_passthrough"

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


def test_map_cabin_and_search_type():
    assert _map_cabin_class("economy") == "ECONOMY"
    assert _map_cabin_class("business") == "BUSINESS"
    assert _map_search_type("best") == "best"
    assert _map_search_type("cheap") == "cheap"
    assert _map_search_type("price") == "cheap"


def test_normalize_flight_offer_new_shape():
    offers = [{
        "departure_time": "01-02-2025 08:34 AM",
        "arrival_time": "01-02-2025 08:45 PM",
        "duration": {"raw": 431, "text": "7 hr 11 min"},
        "flights": [{
            "departure_airport": {
                "airport_name": "John F. Kennedy International Airport",
                "airport_code": "JFK",
                "time": "2025-2-1 08:34",
            },
            "arrival_airport": {
                "airport_name": "Heathrow Airport",
                "airport_code": "LHR",
                "time": "2025-2-1 20:45",
            },
            "duration": 431,
            "airline": "JetBlue",
            "flight_number": "B6 1107",
            "aircraft": "Airbus A321neo",
        }],
        "price": 569,
        "stops": 0,
        "next_token": "tok123",
        "booking_token": "BOOK_TOK",
    }]
    result = _normalize_flight_offer(1, offers, retun_assign=False)
    assert len(result) == 1
    offer = result[0]
    assert offer["price"] == 569
    assert offer["duration_minutes"] == 431
    assert offer["airline_code"] == "B6"
    assert offer["airline_name"] == "JetBlue"
    assert offer["next_token"] == "tok123"
    assert offer["booking_token"] == "BOOK_TOK"
    assert offer["detailToken"] == "BOOK_TOK"
    assert offer["Offer_ID"].startswith("FL-")
    seg = offer["segments"][0]
    assert seg["departure_airport_code"] == "JFK"
    assert seg["arrival_airport_code"] == "LHR"
    assert seg["flight_number"] == "B6 1107"


def test_normalize_flight_offers_reads_booking_token():
    items = normalize_flight_offers([{
        "Offer_ID": "FL-TEST1",
        "price": 100,
        "airline_name": "Delta",
        "booking_token": "BT123",
        "departure_airport_code": "JFK",
        "arrival_airport_code": "LHR",
    }])
    assert len(items) == 1
    assert items[0]["detail_token"] == "BT123"


def test_normalize_flight_offers_pair_inbound_token():
    items = normalize_flight_offers([{
        "Offer_ID": "FL-PAIR1",
        "price": 300,
        "outbound": {"departure_airport_code": "SGN"},
        "inbound": {
            "booking_token": "INB_TOK",
            "departure_airport_code": "DAD",
        },
    }])
    assert items[0]["detail_token"] == "INB_TOK"


@patch("utils.api_client_flight._booking_get")
def test_get_booking_link_details_then_url(mock_booking_get):
    booking_url = (
        "https://www.delta.com/flight-search/search?cabin=BASIC-ECONOMY&price=1068.51"
    )

    def _fake_get(header, path, params, retries=2):
        if path == FLIGHT_BOOKING_DETAILS_ENDPOINT:
            assert params["booking_token"] == "BOOK_TOK"
            assert "currency" in params
            assert "language_code" in params
            assert "country_code" in params
            return [
                {
                    "id": "DL",
                    "title": "Delta",
                    "website": "www.delta.com",
                    "price": 1069,
                    "is_airline": True,
                    "token": "PARTNER_TOK",
                },
                {
                    "id": "DL",
                    "title": "Delta",
                    "website": "www.delta.com",
                    "price": 1319,
                    "is_airline": True,
                    "token": None,
                },
            ]
        if path == FLIGHT_BOOKING_URL_ENDPOINT:
            assert params["token"] == "PARTNER_TOK"
            return booking_url
        raise AssertionError(f"unexpected path {path}")

    mock_booking_get.side_effect = _fake_get

    result = get_booking_link_from_api(detailToken="BOOK_TOK", currency="USD")

    assert result["source"] == "google_flights2_getBookingDetails"
    assert len(result["booking_options"]) == 1
    opt = result["booking_options"][0]
    assert opt["airlineName"] == "Delta"
    assert opt["partner"] == "Delta"
    assert opt["airline_id"] == "DL"
    assert opt["domain"] == "www.delta.com"
    assert opt["bookingPrice"] == 1069
    assert opt["bookingLink"] == booking_url
    assert opt["is_airline"] is True
    paths = [c.args[1] for c in mock_booking_get.call_args_list]
    assert paths == [FLIGHT_BOOKING_DETAILS_ENDPOINT, FLIGHT_BOOKING_URL_ENDPOINT]


@patch("utils.api_client_flight.search_flight_location_from_api")
@patch("utils.api_client_flight._booking_get")
def test_search_one_way_uses_search_flights(mock_booking_get, mock_location):
    mock_location.side_effect = lambda query: {"code": query.upper(), "id": query.upper()}
    mock_booking_get.return_value = {
        "topFlights": [{
            "price": 100,
            "stops": 0,
            "duration": {"raw": 120, "text": "2 hr"},
            "departure_time": "05-04-2026 07:50 AM",
            "arrival_time": "05-04-2026 10:10 AM",
            "flights": [{
                "departure_airport": {
                    "airport_code": "SGN",
                    "airport_name": "Tan Son Nhat",
                    "time": "2026-4-5 07:50",
                },
                "arrival_airport": {
                    "airport_code": "DAD",
                    "airport_name": "Da Nang",
                    "time": "2026-4-5 10:10",
                },
                "airline": "VietJet",
                "flight_number": "VJ 120",
                "duration": 120,
            }],
            "next_token": None,
        }],
        "otherFlights": [],
    }

    result = search_one_way_flights_from_api(
        origin="SGN",
        destination="DAD",
        departure_date="05/09/2030",
        adults=1,
    )

    mock_booking_get.assert_called_once()
    args = mock_booking_get.call_args[0]
    assert args[0] == "google_flight"
    assert args[1] == FLIGHT_SEARCH_ENDPOINT
    params = args[2]
    assert params["departure_id"] == "SGN"
    assert params["arrival_id"] == "DAD"
    assert params["travel_class"] == "ECONOMY"
    assert "return_date" not in params or params.get("return_date") is None
    assert result[0]["source"] == "google_flights2_searchFlights"
    assert result[0]["topFlights"][0]["airline_code"] == "VJ"


@patch("utils.api_client_flight.search_flight_location_from_api")
@patch("utils.api_client_flight._booking_get")
def test_roundtrip_uses_get_next_flights(mock_booking_get, mock_location):
    mock_location.side_effect = lambda query: {"code": query.upper(), "id": query.upper()}

    def _fake_get(header, path, params, retries=2):
        if path == FLIGHT_SEARCH_ENDPOINT:
            return {
                "topFlights": [{
                    "price": 200,
                    "stops": 0,
                    "duration": {"raw": 100, "text": "1 hr"},
                    "departure_time": "05-09-2026 08:00 AM",
                    "arrival_time": "05-09-2026 09:40 AM",
                    "next_token": "NEXT_TOK",
                    "flights": [{
                        "departure_airport": {
                            "airport_code": "SGN",
                            "airport_name": "SGN",
                            "time": "2026-9-5 08:00",
                        },
                        "arrival_airport": {
                            "airport_code": "DAD",
                            "airport_name": "DAD",
                            "time": "2026-9-5 09:40",
                        },
                        "airline": "VN",
                        "flight_number": "VN 100",
                        "duration": 100,
                    }],
                }],
                "otherFlights": [],
            }
        if path == FLIGHT_NEXT_ENDPOINT:
            assert params["next_token"] == "NEXT_TOK"
            assert params["show_hidden"] == "1"
            assert "currency" in params
            assert "language_code" in params
            assert "country_code" in params
            return {
                "topFlights": [{
                    "price": 350,
                    "stops": 0,
                    "duration": {"raw": 100, "text": "1 hr"},
                    "departure_time": "07-09-2026 08:00 AM",
                    "arrival_time": "07-09-2026 09:40 AM",
                    "flights": [{
                        "departure_airport": {
                            "airport_code": "DAD",
                            "airport_name": "DAD",
                            "time": "2026-9-7 08:00",
                        },
                        "arrival_airport": {
                            "airport_code": "SGN",
                            "airport_name": "SGN",
                            "time": "2026-9-7 09:40",
                        },
                        "airline": "VN",
                        "flight_number": "VN 101",
                        "duration": 100,
                    }],
                }],
                "otherFlights": [],
            }
        raise AssertionError(f"unexpected path {path}")

    mock_booking_get.side_effect = _fake_get

    result = search_roundtrip_flights_from_api(
        origin="SGN",
        destination="DAD",
        departure_date="05/09/2030",
        return_date="07/09/2030",
        adults=1,
    )

    paths = [c.args[1] for c in mock_booking_get.call_args_list]
    assert FLIGHT_SEARCH_ENDPOINT in paths
    assert FLIGHT_NEXT_ENDPOINT in paths
    search_params = mock_booking_get.call_args_list[0].args[2]
    assert search_params["return_date"] is not None
    assert result[0]["source"] == "google_flights2_searchFlights"
    assert result[0]["topFlights"][0]["outbound"]["departure_airport_code"] == "SGN"
    assert result[0]["topFlights"][0]["inbound"]["departure_airport_code"] == "DAD"


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
            departure_date="05/09/2030",
            return_date="07/09/2030",
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
