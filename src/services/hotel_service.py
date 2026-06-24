# src/services/hotel_service.py

from typing import Optional

from utils.api_client_hotel import (
    search_hotel_from_api,
    get_hotel_room_list_from_api,
    # book_hotel_room_from_api,
    # cancel_hotel_booking_from_api,
)


def search_hotels(
    location: Optional[str] = None,
    name: Optional[str] = None,
    price_tier: Optional[str] = None,
    price: Optional[int] = None,
    rating: Optional[float] = None,
    checkin_date: Optional[str] = None,
    checkout_date: Optional[str] = None,
    adults: int = 2,
    children_age: Optional[str] = None,
    room_qty: int = 1,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
    limit: int = 10,
) -> list[dict]:
    if not location and not name:
        return [{"error": "Bạn cần cung cấp location hoặc name."}]

    return search_hotel_from_api(
        location=location,
        name=name,
        price_tier=price_tier,
        price=price,
        rating=rating,
        checkin_date=checkin_date,
        checkout_date=checkout_date,
        adults=adults,
        children_age=children_age,
        room_qty=room_qty,
        price_min=price_min,
        price_max=price_max,
        limit=limit,
    )

def get_hotel_room_list(
    hotel_id: str | int,
    checkin_date: str,
    checkout_date: str,
    adults: int = 2,
    children_age: Optional[str] = None,
    room_qty: int = 1,
    price: Optional[int] = None,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
    limit: int = 20,
) -> list[dict]:
    if not hotel_id:
        return [{"error": "Bạn cần cung cấp hotel_id (external_hotel_id)."}]
    return get_hotel_room_list_from_api(
        hotel_id=hotel_id,
        checkin_date=checkin_date,
        checkout_date=checkout_date,
        adults=adults,
        children_age=children_age,
        room_qty=room_qty,
        price=price,
        price_min=price_min,
        price_max=price_max,
        limit=limit,
    )
# def search_hotel_rooms(
#     hotel_name: Optional[str] = None,
#     room_type: Optional[str] = None,
#     price: Optional[int] = None,
#     price_max: Optional[int] = None,
#     price_min: Optional[int] = None,
#     capacity: Optional[int] = None,
# ) -> list[dict] | str:
#     if not hotel_name:
#         return "Bạn cần cung cấp tên khách sạn."

#     return search_hotel_rooms_from_api(
#         hotel_name=hotel_name,
#         room_type=room_type,
#         price=price,
#         price_max=price_max,
#         price_min=price_min,
#         capacity=capacity,
#     )


# def book_hotel_room(
#     room_id: int,
#     hotel_id: int,
#     checkin_date: str,
#     checkout_date: str,
#     total_price: int,
# ) -> dict:
#     return book_hotel_room_from_api(
#         room_id=room_id,
#         hotel_id=hotel_id,
#         checkin_date=checkin_date,
#         checkout_date=checkout_date,
#         total_price=total_price,
#     )


# def cancel_hotel_booking(booking_id: int):
#     return cancel_hotel_booking_from_api(booking_id)