from utils.api_client_hotel import (
    _filter_items_by_per_night_price,
    _per_night_to_stay_total_bounds,
)


def test_per_night_filter_keeps_hotels_in_budget_band():
    hotels = [
        {"name": "cheap", "price": 591_300, "price_per_night": 591_300, "total_price": 1_182_600},
        {"name": "mid", "price": 1_200_000, "price_per_night": 1_200_000, "total_price": 2_400_000},
        {"name": "high", "price": 2_500_000, "price_per_night": 2_500_000, "total_price": 5_000_000},
    ]

    filtered = _filter_items_by_per_night_price(
        hotels, price_min=1_000_000, price_max=2_000_000
    )

    assert [h["name"] for h in filtered] == ["mid"]


def test_per_night_filter_does_not_use_stay_total():
    # Old bug: total 1.18M would pass a 1–2M band even though per-night is ~591k.
    hotels = [
        {"name": "under", "price": 591_300, "total_price": 1_182_600},
    ]

    filtered = _filter_items_by_per_night_price(
        hotels, price_min=1_000_000, price_max=2_000_000
    )

    assert filtered == []


def test_per_night_bounds_convert_to_stay_total_for_booking_api():
    assert _per_night_to_stay_total_bounds(1_000_000, 2_000_000, nights=2) == (
        2_000_000,
        4_000_000,
    )
    assert _per_night_to_stay_total_bounds(None, 1_000_000, nights=3) == (
        None,
        3_000_000,
    )
