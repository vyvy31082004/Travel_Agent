import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agents.primary.domain_scope import build_domain_scoped_state
from memory.domain_runtime import extract_ordinal_position
from services.reference_resolver import ClarificationNeeded, resolve_item_reference


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


def _hotel_then_tour_state() -> dict:
    """Turn 1 hotel search, turn 2 tour search — both lists still in State."""
    return {
        "visible_results": {
            "req_hotel": {
                "search_id": "search-hotel",
                "domain": "hotel",
                "displayed_item_ids": ["H1", "H2", "H3"],
            },
            "req_tour": {
                "search_id": "search-tour",
                "domain": "tour",
                "displayed_item_ids": ["T1", "T2"],
            },
        },
        "latest_request_by_domain": {
            "hotel": "req_hotel",
            "tour": "req_tour",
        },
        # Latest turn was tour, but hotel list must still resolve.
        "active_request_id": "req_tour",
    }


def test_hotel_ordinal_after_tour_search_uses_hotel_list_not_active_tour():
    """Turn 3: 'khách sạn thứ 2' must map to hotel H2, not tour T2."""
    state = _hotel_then_tour_state()
    user_text = "Cho tôi chi tiết khách sạn thứ 2"

    position = extract_ordinal_position(user_text)
    assert position == 2

    resolved = resolve_item_reference(state, domain="hotel", position=position)
    assert not isinstance(resolved, ClarificationNeeded)
    assert resolved.item_id == "H2"
    assert resolved.search_id == "search-hotel"
    assert resolved.request_id == "req_hotel"
    assert resolved.domain == "hotel"
    assert resolved.position == 2


def test_ordinal_without_domain_falls_back_to_active_tour_list():
    """Bare 'cái thứ 2' uses active_request_id (tour), not the older hotel list."""
    state = _hotel_then_tour_state()
    position = extract_ordinal_position("cái thứ 2")
    assert position == 2

    resolved = resolve_item_reference(state, domain=None, position=position)
    assert not isinstance(resolved, ClarificationNeeded)
    assert resolved.item_id == "T2"
    assert resolved.domain == "tour"
    assert resolved.search_id == "search-tour"


def test_hotel_scoped_state_then_ordinal_ignores_tour_list():
    """Hotel agent only sees hotel visible_results; ordinal still resolves H2."""
    state = _hotel_then_tour_state()
    scoped = build_domain_scoped_state(state, "hotel")

    assert "req_hotel" in scoped["visible_results"]
    assert "req_tour" not in scoped["visible_results"]
    assert scoped["active_request_id"] == "req_hotel"

    resolved = resolve_item_reference(scoped, domain="hotel", position=2)
    assert resolved.item_id == "H2"
    assert resolved.search_id == "search-hotel"
