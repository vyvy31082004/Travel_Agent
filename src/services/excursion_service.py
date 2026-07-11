# src/services/hotel_service.py

from typing import Optional

from utils.api_client_excur import (
    search_attractions_from_api,
    fetch_attraction_details_from_api,
    fetch_attraction_reviews_from_api
)


def search_attractions(
    location: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    sort_by: str = "trending",
    page: int = 1,
    type_filters: Optional[str] = None,
    price_filters: Optional[str] = None,
    ufi_filters: Optional[str] = None,
    label_filters: Optional[str] = None,
    limit: int = 10,
) -> list[dict]:
    if not location:
        return [{"error": "Bạn cần cung cấp location."}]

    return search_attractions_from_api(
        location=location,
        start_date=start_date,
        end_date=end_date,
        sort_by=sort_by,
        page=page,
        type_filters=type_filters,
        price_filters=price_filters,
        ufi_filters=ufi_filters,
        label_filters=label_filters,
        limit=limit,
    )

def fetch_attraction_details(slug: str):
    return fetch_attraction_details_from_api(
        slug=slug,
    )
def fetch_attraction_reviews(id: str ):
    return fetch_attraction_reviews_from_api(
        id=id,
    )