import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from services.reference_resolver import resolve_item_reference


def test_ordinal_uses_display_order_from_visible_results():
    state = {
        "visible_results": {
            "req_hotel_1": {
                "search_id": "search-1",
                "domain": "hotel",
                "displayed_item_ids": ["872579", "1111660"],
            }
        },
        "latest_request_by_domain": {"hotel": "req_hotel_1"},
        "active_request_id": "req_hotel_1",
    }
    resolved = resolve_item_reference(state, domain="hotel", position=2)
    assert resolved.item_id == "1111660"
    assert resolved.position == 2


def test_excursion_domain_alias_matches_tour_visible_results():
    state = {
        "visible_results": {
            "req_tour_1": {
                "search_id": "search-tour",
                "domain": "tour",
                "displayed_item_ids": ["att-1", "att-2"],
            }
        },
        "latest_request_by_domain": {"tour": "req_tour_1"},
    }
    resolved = resolve_item_reference(state, domain="excursion", position=1)
    assert resolved.item_id == "att-1"
    assert resolved.domain == "tour"
