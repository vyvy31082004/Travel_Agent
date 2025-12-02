import sqlite3
from langchain_core.tools import tool
from typing import Optional
from utils.constant import RANGE_PRICE_TRIP
from dotenv import load_dotenv
# Import all necessary functions from the new api_client
from utils.api_client_excur import (
    search_trip_from_api,
    fetch_excursion_info_from_api,
    book_excursion_in_api,
    cancel_tour_booking_in_api,
    update_tour_booking_in_api
    # cancel_excursion_in_api,
    # fetch_excursion_info_from_api,
    # fetch_excursion_booking_info_from_api,
)

# Keep utility functions if they are still needed
from utils.utils import to_date

load_dotenv()

# def calculate_total_price(price: int, people: int) -> float:
#     return price * people

# def fetch_excursion_info(trip_id : int) -> dict:
#     """
#         Return information of trip.
#     """
#     conn = sqlite3.connect(DB_PATH)
#     curr = conn.cursor()
#     # Lấy booking
#     curr.execute("""
#         SELECT name, location, keywords, price
#         FROM trip_recommendations
#         WHERE id = ?
#     """, (trip_id,))
#     trip = curr.fetchone()
#     if not trip:
#         conn.close()
#         return {}
#     name, location, keywords, price = trip
#     return {
#         "name": name,
#         "location": location,
#         "keywords": keywords,
#         "price": price
#     }

# def fetch_excursion_booking_info(booking_id: int) -> dict:
#     """
#     Return information of booking excursion and information of trip.

#     """
#     conn = sqlite3.connect(DB_PATH)
#     curr = conn.cursor()

#     # Lấy booking
#     curr.execute("""
#         SELECT trip_id, date, people, total_price
#         FROM trip_bookings
#         WHERE booking_id = ?
#     """, (booking_id,))
#     booking = curr.fetchone()
#     if not booking:
#         conn.close()
#         return {}
#     trip_id, date_str, people, total_price = booking
#     result = {
#             "booking_id": booking_id,
#             "trip_id": trip_id,
#             "date": date_str,
#             "people": people,
#             "total_price": total_price if total_price is not None else None,
#         }
#     details = fetch_excursion_info(trip_id)
#     if details:
#         result.update({
#                 "name": details["name"],
#                 "location": details["location"],
#                 "keywords": details["keywords"],
#                 "price": details["price"]
#             })
#     return result
    
@tool
def search_trip(
    location: Optional[str] = None,
    name: Optional[str] = None,
    keywords: Optional[str] = None,
    details: Optional[str] = None,
    price: Optional[int] = None,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None
) -> list[dict]:
    """
    Find trips based on location, name, and keywords, details, price, price min, price max.

    """
    return search_trip_from_api(location, name, keywords, details, price, price_min, price_max)
    


@tool
def book_excursion(
    date: str,
    people : int,
    trip_name : str,
    ) -> str:
    """
    Book an excursion by trip id, trip name, date, number of people.

    """

    excur_info = fetch_excursion_info_from_api(trip_name)
    if not excur_info:
        return f"Không tìm thấy tour '{trip_name}'."
        
    excur_price = excur_info["price"]

    try:
        booking_result = book_excursion_in_api(
            excur_id=excur_info["id"],
            date=date,
            people=people,
            total_price=excur_price * people,
        )
        return f"Đặt tour thành công! Mã đặt tour của bạn là {booking_result.get('booking_id')}. Tổng chi phí là {excur_price*people:,.0f} VNĐ."
    except Exception as e:
        return f"Đã xảy ra lỗi khi đặt tour: {e}"

@tool 
def update_tour(
    booking_id: int,
    people: Optional[int] = None, 
    date: Optional[str] = None,
    ) -> str:
    """
    Update booking tour about number of people and/or date tour by booking id.

    """
    try:
        new_booking = update_tour_booking_in_api(booking_id, new_people=people, new_date=date)
        if new_booking:
            return f"Cập nhật thành công cho mã đặt tour {booking_id}."
        else:
            return f"Không tìm thấy mã đặt tour {booking_id} để cập nhật."
    except Exception as e:
        return f"Đã xảy ra lỗi khi cập nhật: {e}"

@tool
def cancel_tour(booking_id: int) -> str:
    """Cancel a tour booking using its booking ID."""
    try:
        success = cancel_tour_booking_in_api(booking_id)
        if success:
            return f"Đã hủy thành công mã đặt tour {booking_id}."
        else:
            return f"Không tìm thấy mã đặt tour {booking_id} để hủy."
    except Exception as e:
        return f"Đã xảy ra lỗi khi hủy đặt tour: {e}"