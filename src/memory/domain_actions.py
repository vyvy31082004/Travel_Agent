from __future__ import annotations

from enum import StrEnum

from memory.long_term import MemoryDomain


class HotelAction(StrEnum):
    SEARCH_HOTELS = "search_hotels"
    GET_HOTEL_DETAILS = "get_hotel_details"
    SELECT_ROOM = "select_room"
    GET_REVIEWS = "get_reviews"
    GENERAL = "general"


class FlightAction(StrEnum):
    SEARCH_ONE_WAY = "search_one_way"
    SEARCH_ROUND_TRIP = "search_round_trip"
    COMPARE_OFFERS = "compare_offers"
    GENERAL = "general"


class ExcursionAction(StrEnum):
    SEARCH_ATTRACTIONS = "search_attractions"
    GET_DETAILS = "get_details"
    BUILD_DAY_PLAN = "build_day_plan"
    GENERAL = "general"


class CarAction(StrEnum):
    SEARCH_CARS = "search_cars"
    COMPARE_CARS = "compare_cars"
    SELECT_CAR = "select_car"
    GENERAL = "general"


DOMAIN_ACTIONS: dict[str, tuple[str, ...]] = {
    MemoryDomain.HOTEL.value: tuple(HotelAction),
    MemoryDomain.FLIGHT.value: tuple(FlightAction),
    MemoryDomain.EXCURSION.value: tuple(ExcursionAction),
    MemoryDomain.CAR.value: tuple(CarAction),
}


def allowed_actions_for_domain(domain: str) -> tuple[str, ...]:
    return DOMAIN_ACTIONS.get(str(domain).strip(), (HotelAction.GENERAL.value,))
