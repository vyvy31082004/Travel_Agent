from memory.normalize import (
    compact_tool_ref,
    normalize_flight_offers,
    normalize_hotel_offers,
)


def test_normalize_hotel_offers_keeps_external_id():
    items = normalize_hotel_offers(
        [
            {
                "external_hotel_id": "123",
                "name": "Hotel A",
                "price": 500000,
                "currency": "VND",
                "photo": "http://x",
            }
        ]
    )
    assert items[0]["item_id"] == "123"
    assert items[0]["payload"]["name"] == "Hotel A"


def test_normalize_flight_offers_from_top_flights():
    items = normalize_flight_offers(
        {
            "topFlights": [
                {
                    "Offer_ID": "FL-A1",
                    "airline_name": "VJ",
                    "detailToken": "tok",
                    "price": 1000,
                }
            ],
            "otherFlights": [],
        }
    )
    assert items[0]["item_id"] == "FL-A1"
    assert items[0]["detail_token"] == "tok"
    assert "detailToken" not in items[0]["payload"]


def test_compact_tool_ref_shape():
    ref = compact_tool_ref(
        request_id="req_1",
        search_id="s1",
        domain="hotel",
        total_results=10,
        displayed_item_ids=["1", "2"],
        labels=[{"item_id": "1", "name": "A"}],
    )
    assert ref["search_id"] == "s1"
    assert ref["displayed_item_ids"] == ["1", "2"]
    assert "labels" in ref
