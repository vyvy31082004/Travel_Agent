import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memory.domain_actions import (
    CarAction,
    ExcursionAction,
    FlightAction,
    HotelAction,
    allowed_actions_for_domain,
)


def test_domain_action_enums_cover_all_domains():
    assert HotelAction.SEARCH_HOTELS.value in allowed_actions_for_domain("hotel")
    assert FlightAction.SEARCH_ONE_WAY.value in allowed_actions_for_domain("flight")
    assert ExcursionAction.SEARCH_ATTRACTIONS.value in allowed_actions_for_domain("excursion")
    assert CarAction.SEARCH_CARS.value in allowed_actions_for_domain("car")
