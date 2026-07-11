import sqlite3
from langchain_core.tools import tool
from typing import Optional
from utils.constant import RANGE_PRICE_TRIP
from dotenv import load_dotenv
from datetime import date, datetime
# Import all necessary functions from the new api_client
# from utils.api_client_excur import (
#     #search_trip_from_api
#     fetch_excursion_info_from_api,
#     book_excursion_in_api,
#     cancel_tour_booking_in_api,
#     update_tour_booking_in_api,
#     # search_attractions_from_api,
#     # fetch_attraction_details_from_api,
#     # fetch_attraction_availability_from_api,
#     # fetch_attraction_reviews_from_api
#     # cancel_excursion_in_api,
#     # fetch_excursion_info_from_api,
#     # fetch_excursion_booking_info_from_api,
# )

# Keep utility functions if they are still needed
from utils.utils import to_date

load_dotenv()


    
# @tool
# def search_trip(
#     location: Optional[str] = None,
#     name: Optional[str] = None,
#     keywords: Optional[str] = None,
#     details: Optional[str] = None,
#     price: Optional[int] = None,
#     price_min: Optional[int] = None,
#     price_max: Optional[int] = None
# ) -> list[dict]:
#     """
#     Find trips based on location, name, and keywords, details, price, price min, price max.

#     """
#     return search_trip_from_api(location, name, keywords, details, price, price_min, price_max)

from langchain_mcp_adapters.client import MultiServerMCPClient

async def get_excursion_tools():
    client = MultiServerMCPClient(
        {
            "excursion": {
                "url": "http://127.0.0.1:8000/sse",
                "transport": "sse",
            }
        }
    )
    tools = await client.get_tools()
    excursion_tool_names = {
        "search_attractions_tool",
        "fetch_attraction_details_tool",
        "fetch_attraction_reviews_tool",
    }
    return [tool for tool in tools if tool.name in excursion_tool_names]


# @tool
# def get_trip_availability(
#     slug: str,
#     date_value: Optional[str] = None,
# ) -> dict:
#     """
#     Get attraction availability by date.
#     Use slug returned by search_trip.
#     """
#     return fetch_attraction_availability_from_api(
#         slug=slug,
#         date_value=date_value,
#     )


# @tool
# def get_trip_reviews(
#     attraction_id: str,
#     page: int = 1,
# ) -> dict:
#     """
#     Get attraction reviews.
#     Use external_attraction_id returned by search_trip.
#     """
#     return fetch_attraction_reviews_from_api(
#         attraction_id=attraction_id,
#         page=page,
#     )
    


# @tool
# def book_excursion(
#     tour_date: str,
#     people : int,
#     trip_name : str,
#     ) -> str:
#     """
#     Book an excursion by trip id, trip name, date, number of people.

#     """
#     if not tour_date:
#         return "Bạn cần cung cấp ngày đặt tour."
#     if not people:
#         return "Bạn cần cung cấp số lượng người."
#     if not trip_name:
#         return "Bạn cần cung cấp tên tour."
#     if to_date(tour_date) < date.today():
#         return "Ngày đặt tour phải sau ngày hiện tại."
#     excur_info = fetch_excursion_info_from_api(trip_name)
#     if not excur_info:
#         return f"Không tìm thấy tour '{trip_name}'."
        
#     excur_price = excur_info["price"]

#     try:
#         booking_result = book_excursion_in_api(
#             excur_id=excur_info["id"],
#             tour_date=tour_date,
#             people=people,
#             total_price=excur_price * people,
#         )
#         return f"Đặt tour thành công! Mã đặt tour của bạn là {booking_result.get('booking_id')}. Tổng chi phí là {excur_price*people:,.0f} VNĐ."
#     except Exception as e:
#         return f"Đã xảy ra lỗi khi đặt tour: {e}"

# @tool 
# def update_tour(
#     booking_id: int,
#     people: Optional[int] = None, 
#     tour_date: Optional[str] = None,
#     ) -> str:
#     """
#     Update booking tour about number of people and/or date tour by booking id.

#     """
#     if not tour_date:
#         return "Bạn cần cung cấp ngày đặt tour."
#     if not people:
#         return "Bạn cần cung cấp số lượng người."
#     if to_date(tour_date) < date.today():
#         return "Ngày đặt tour phải sau ngày hiện tại."
#     if not booking_id:
#         return "Bạn cần cung cấp mã đặt tour."
#     try:
#         new_booking = update_tour_booking_in_api(booking_id, new_people=people, new_date=date)
#         if new_booking:
#             return f"Cập nhật thành công cho mã đặt tour {booking_id}."
#         else:
#             return f"Không tìm thấy mã đặt tour {booking_id} để cập nhật."
#     except Exception as e:
#         return f"Đã xảy ra lỗi khi cập nhật: {e}"

# @tool
# def cancel_tour(booking_id: int) -> str:
#     """Cancel a tour booking using its booking ID."""
#     if not booking_id:
#         return "Bạn cần cung cấp mã đặt tour."
#     try:
#         success = cancel_tour_booking_in_api(booking_id)
#         if success:
#             return f"Đã hủy thành công mã đặt tour {booking_id}."
#         else:
#             return f"Không tìm thấy mã đặt tour {booking_id} để hủy."
#     except Exception as e:
#         return f"Đã xảy ra lỗi khi hủy đặt tour: {e}"