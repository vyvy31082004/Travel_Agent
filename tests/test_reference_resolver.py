from services.reference_resolver import ClarificationNeeded, resolve_item_reference
from memory.domain_runtime import extract_ordinal_position


def test_resolve_position_to_item_id():
    state = {
        "latest_request_by_domain": {"flight": "req_flight_001"},
        "visible_results": {
            "req_flight_001": {
                "search_id": "search_flight_001",
                "displayed_item_ids": [
                    "flight_offer_81",
                    "flight_offer_37",
                    "flight_offer_52",
                ],
                "domain": "flight",
            }
        },
    }
    resolved = resolve_item_reference(state, domain="flight", position=2)
    assert not isinstance(resolved, ClarificationNeeded)
    assert resolved.item_id == "flight_offer_37"
    assert resolved.position == 2


def test_resolve_ambiguous_without_domain():
    state = {
        "visible_results": {
            "req_flight_001": {
                "search_id": "s1",
                "displayed_item_ids": ["a", "b"],
                "domain": "flight",
            },
            "req_hotel_001": {
                "search_id": "s2",
                "displayed_item_ids": ["h1", "h2"],
                "domain": "hotel",
            },
        }
    }
    resolved = resolve_item_reference(state, position=2)
    assert isinstance(resolved, ClarificationNeeded)


def test_extract_ordinal_vietnamese():
    assert extract_ordinal_position("Cho tôi xem chi tiết khách sạn thứ 2") == 2
    assert extract_ordinal_position("xem cái thứ 3 giúp mình") == 3
    assert extract_ordinal_position("hotel #1 details") == 1
