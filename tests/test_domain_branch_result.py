from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from agents.primary.agent import _format_domain_branch_results
from agents.primary.domain_result import build_domain_branch_result


def test_excursion_branch_includes_tour_visible_results() -> None:
    branch = build_domain_branch_result(
        domain="excursion",
        summary="Tours in Da Nang",
        visible_results={
            "req_1": {
                "search_id": "search-abc",
                "displayed_item_ids": ["PRFhLYK7act7"],
                "domain": "tour",
            }
        },
        domain_action="search_attractions",
    )
    assert len(branch.options) == 1
    assert branch.options[0]["search_id"] == "search-abc"


def test_format_domain_branch_results_lists_all_displayed_item_ids() -> None:
    branch = build_domain_branch_result(
        domain="hotel",
        summary="Hotels in Da Nang",
        visible_results={
            "req_1": {
                "search_id": "search-hotel",
                "displayed_item_ids": ["7006996", "4263727", "123"],
                "domain": "hotel",
            }
        },
    )
    formatted = _format_domain_branch_results([branch.to_dict()])
    assert "include ALL" in formatted
    assert "7006996" in formatted
    assert "4263727" in formatted
    assert "123" in formatted
    assert "(3 items" in formatted
