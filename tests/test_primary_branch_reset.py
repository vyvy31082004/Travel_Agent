import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agents.primary.state import (
    RESET_BRANCH_RESULTS,
    merge_branch_results,
)


def test_merge_branch_results_appends_within_turn():
    left = [{"domain": "flight", "id": "f1"}]
    right = {"domain": "hotel", "id": "h1"}
    assert merge_branch_results(left, right) == [
        {"domain": "flight", "id": "f1"},
        {"domain": "hotel", "id": "h1"},
    ]


def test_reset_marker_clears_prior_turn_results():
    prior = [{"domain": "flight", "id": "old"}]
    # A new turn's recall node emits the reset marker.
    cleared = merge_branch_results(prior, RESET_BRANCH_RESULTS)
    assert cleared == []
    # Current-turn results then accumulate on the cleared base.
    current = merge_branch_results(cleared, {"domain": "hotel", "id": "new"})
    assert current == [{"domain": "hotel", "id": "new"}]
    assert not any(item["id"] == "old" for item in current)


def test_none_preserves_existing():
    prior = [{"domain": "car", "id": "c1"}]
    assert merge_branch_results(prior, None) == prior
