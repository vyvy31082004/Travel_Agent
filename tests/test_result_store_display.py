import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from repositories.result_store import ResultStoreRepository


def test_row_to_item_includes_display_fields():
    row = {
        "item_id": "1111660",
        "position": 2,
        "api_position": 6,
        "eligible": True,
        "payload": {"name": "Sea Star", "price": 860200},
    }
    item = ResultStoreRepository._row_to_item(row)
    assert item["item_id"] == "1111660"
    assert item["position"] == 2
    assert item["api_position"] == 6
    assert item["eligible"] is True
    assert item["name"] == "Sea Star"


def test_row_to_item_without_optional_display_fields():
    row = {
        "item_id": "flight_1",
        "position": 1,
        "payload": {"offer_id": "FL-ABC"},
    }
    item = ResultStoreRepository._row_to_item(row)
    assert item["item_id"] == "flight_1"
    assert item["position"] == 1
    assert "api_position" not in item
    assert "eligible" not in item
