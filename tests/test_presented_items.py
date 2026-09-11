import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memory.presented_items import extract_presented_item_ids


def test_extract_hotel_ids_from_summary_text():
    text = """
    * **Sea Star Resort** (ID: 1111660)
    * **Coral Bay Resort** (ID: 872579)
    """
    presented = extract_presented_item_ids(
        ai_text=text,
        domain="hotel",
        known_item_ids=["1111660", "872579", "4632878"],
    )
    assert presented == ["1111660", "872579"]


def test_extract_flight_offer_ids():
    text = "Offer_ID: FL-A8B2C is the best option. Also see FL-Z9Y8X."
    presented = extract_presented_item_ids(
        ai_text=text,
        domain="flight",
        known_item_ids=["FL-A8B2C", "FL-Z9Y8X", "FL-OTHER"],
    )
    assert presented == ["FL-A8B2C", "FL-Z9Y8X"]


def test_extract_excursion_ids_with_tour_domain():
    text = "Tour A external_attraction_id: att-99 and (ID: att-12)"
    presented = extract_presented_item_ids(
        ai_text=text,
        domain="tour",
        known_item_ids=["att-99", "att-12", "att-00"],
    )
    assert presented == ["att-99", "att-12"]


def test_extract_ignores_unknown_ids():
    text = "Hotel (ID: 999999) and (ID: 1111660)"
    presented = extract_presented_item_ids(
        ai_text=text,
        domain="hotel",
        known_item_ids=["1111660"],
    )
    assert presented == ["1111660"]


def test_extract_fallback_by_name():
    text = "I recommend Sea Star Resort for your stay."
    presented = extract_presented_item_ids(
        ai_text=text,
        domain="hotel",
        known_item_ids=["1111660"],
        known_items=[
            {
                "item_id": "1111660",
                "name": "Sea Star Resort",
                "price": 860200,
            }
        ],
    )
    assert presented == ["1111660"]
