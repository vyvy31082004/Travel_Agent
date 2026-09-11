from __future__ import annotations

import asyncio
from types import SimpleNamespace

from memory.normalize import normalize_flight_offers
from memory.tool_wrapper import persist_search_tool_result


def test_normalize_roundtrip_preserves_outbound_and_inbound():
    raw = [{
        "topFlights": [{
            "Offer_ID": "FL-ROUND1",
            "price": 3_000_000,
            "booking_token": "book-token",
            "outbound": {
                "airline_code": "VN",
                "airline_name": "Vietnam Airlines",
                "departure_airport_code": "SGN",
                "arrival_airport_code": "DAD",
                "departure_time": "08:00",
                "departure_date": "2026-10-20",
                "arrival_time": "09:30",
                "arrival_date": "2026-10-20",
                "stops": 0,
                "segments": [{"flight_number": "VN100"}],
            },
            "inbound": {
                "airline_code": "VN",
                "departure_airport_code": "DAD",
                "arrival_airport_code": "SGN",
                "departure_time": "18:00",
                "departure_date": "2026-10-23",
            },
        }],
        "otherFlights": [],
    }]

    items = normalize_flight_offers(raw)

    assert len(items) == 1
    item = items[0]
    assert item["item_id"] == "FL-ROUND1"
    assert item["detail_token"] == "book-token"
    assert item["payload"]["departure_airport_code"] == "SGN"
    assert item["payload"]["arrival_airport_code"] == "DAD"
    assert item["payload"]["outbound"]["segments"][0]["flight_number"] == "VN100"
    assert item["payload"]["inbound"]["departure_airport_code"] == "DAD"


def test_normalize_outbound_only_pair_preserves_incomplete_warning():
    items = normalize_flight_offers([{
        "topFlights": [{
            "Offer_ID": "FL-OUTBOUND",
            "price": 1_000_000,
            "outbound": {
                "departure_airport_code": "SGN",
                "arrival_airport_code": "DAD",
            },
            "inbound": None,
            "warning": "Không có lựa chọn chiều về.",
        }],
        "otherFlights": [],
    }])

    assert items[0]["payload"]["warning"] == "Không có lựa chọn chiều về."
    assert items[0]["payload"]["complete_roundtrip"] is False


def test_normalize_flight_skips_upstream_error_items():
    assert normalize_flight_offers([{"error": "provider unavailable"}]) == []


def test_persist_search_returns_upstream_error_without_writing():
    class FailIfCalledRepository:
        async def save_search(self, **kwargs):
            raise AssertionError("upstream errors must not be persisted")

    result = asyncio.run(
        persist_search_tool_result(
            "search_one_way_flights_tool",
            [{"error": "provider unavailable"}],
            {"configurable": {"user_id": "u", "thread_id": "t"}},
            FailIfCalledRepository(),
        )
    )

    assert result == {"error": "provider unavailable"}
