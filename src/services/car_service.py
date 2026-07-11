
from typing import Optional

from utils.api_client_car import (
    search_cars_from_api,
    search_car_details,
)


def search_cars(
    start_ms: int | str,
    end_ms: int | str,
    address: str,
    user_needs : str,
    min_price: int = 0,
    max_price: int = 0,
    limit: int = 10,
) -> list[dict]:
    return search_cars_from_api(
        start_ms=start_ms,
        end_ms=end_ms,
        address=address,
        user_needs=user_needs,
        min_price=min_price,
        max_price=max_price,
        limit=limit,
    )

def get_car_details(car_name: str,car_id: str) -> dict:
    return search_car_details(car_name, car_id)