import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agents.primary.domain_scope import build_domain_scoped_state, compact_domain_state


def test_build_domain_scoped_state_excludes_global_memory():
    state = {
        "user_id": "u1",
        "memory_context": "global profile",
        "visible_results": {
            "r1": {"domain": "hotel", "search_id": "s1"},
            "r2": {"domain": "flight", "search_id": "s2"},
        },
        "latest_request_by_domain": {"hotel": "r1", "flight": "r2"},
        "delegated_request": "find hotel",
        "trip_plan_user_message": "plan trip",
    }
    scoped = build_domain_scoped_state(state, "hotel")
    assert "memory_context" not in scoped
    assert "r1" in scoped["visible_results"]
    assert "r2" not in scoped["visible_results"]


def test_resolve_user_query_prefers_delegated_request():
    from agents.primary.domain_scope import resolve_user_query

    state = {
        "delegated_request": "Tìm chuyến bay tối",
        "user_query": "Lên kế hoạch Đà Nẵng: khách sạn, chuyến bay, thuê xe, tour",
        "trip_plan_user_message": "Lên kế hoạch Đà Nẵng",
    }
    assert resolve_user_query(state) == "Tìm chuyến bay tối"


def test_compact_domain_state_filters_cross_domain_entries():
    state = {
        "visible_results": {
            "h1": {"domain": "hotel"},
            "f1": {"domain": "flight"},
        }
    }
    compact = compact_domain_state(state, "hotel")
    assert list(compact["visible_results"].keys()) == ["h1"]
