from datetime import date, datetime
from typing import Optional
from langchain_core.tools import tool
from dotenv import load_dotenv
import os
from utils.api_client_hotel import (
    search_hotel_from_api,
    search_hotel_rooms_from_api,
    fetch_hotel_room_info_from_api,
    check_realse_room_from_api,
    book_hotel_room_from_api,
    update_hotel_booking_from_api,
    fetch_booking_info_from_api,
    cancel_hotel_booking_from_api
)

from utils.utils import to_date

load_dotenv()

@tool
def search_hotels(
    location: Optional[str] = None, 
    name: Optional[str] = None, 
    price_tier: Optional[str] = None,
    rating: Optional[float] = None
) -> list[dict]:
    """Find hotels based on location, name, price_tier, and rating."""
    return search_hotel_from_api(location, name, price_tier, rating)

@tool
def search_hotel_rooms(
    hotel_name: Optional[str] = None,
    room_type: Optional[str] = None,
    price: Optional[int] = None,
    price_max: Optional[int] = None,
    price_min: Optional[int] = None,
    capacity: Optional[int] = None,
) -> list[dict]:
    """Find hotel rooms based on hotel name, room type, price, price min, price max and capacity."""
    return search_hotel_rooms_from_api(hotel_name, room_type, price, price_max, price_min, capacity)    

@tool
def book_hotel_room(
    checkin_date: str,
    checkout_date: str,
    room_type: Optional[str] = None,
    hotel_name: Optional[str] = None,
    hotel_id: Optional[int] = None,
) -> str:
    """
    Book a hotel room based on checkin date, checkout date, room type,  hotel name and hotel id.
    First, find the room id and hotel id, then check capacity and price before booking.
    """
    room_info = fetch_hotel_room_info_from_api(hotel_name, room_type, None)
    if not room_info:
        return f"Không tìm thấy phòng '{room_type}' tại khách sạn '{hotel_name}'."
    room_id = room_info["room_id"]
    hotel_id = room_info["hotel_id"]
    unavailable_room = check_realse_room_from_api("book", None, room_id, checkin_date, checkout_date)
    if unavailable_room:
        return f"Phòng '{room_type}' tại khách sạn '{hotel_name}' đã được đặt trong khoảng thời gian '{checkin_date}' - '{checkout_date}'."
   
    room_price = room_info["price"]
    total_price = room_price * (to_date(checkout_date) - to_date(checkin_date)).days
    try:
        booking_result = book_hotel_room_from_api(
            room_id=room_id,
            hotel_id=hotel_id,
            checkin_date=to_date(checkin_date).isoformat(),
            checkout_date=to_date(checkout_date).isoformat(),
            total_price=total_price
        )
        return f"Đặt phòng thành công! Giá phòng là {room_price} VNĐ. Mã đặt phòng của bạn là {booking_result.get('booking_id')}. Tổng chi phí là {booking_result.get('total_price')} VNĐ."
    except Exception as e:
        return f"Đã xảy ra lỗi khi đặt phòng: {e}"

@tool
def update_hotel_booking(
    booking_id: int,
    checkin_date: str,
    checkout_date: str,
) -> str:
    """
    Update a hotel booking based on booking id, checkin date and checkout date.
    
    """
    booking_status = fetch_booking_info_from_api(booking_id)["status"]
    if booking_status == "cancelled":
        return f"Không thể cập nhật mã đặt phòng {booking_id} vì đã bị hủy."
    unavailable_room = check_realse_room_from_api("update", booking_id, None, checkin_date, checkout_date)
    if unavailable_room:
        return f"Phòng đã được đặt trong khoảng thời gian '{checkin_date}' - '{checkout_date}'."
    try:
        room_id = fetch_booking_info_from_api(booking_id)["room_id"]
        room_info = fetch_hotel_room_info_from_api(None, None, room_id)
        room_price = room_info["price"]
        total_price = room_price * (to_date(checkout_date) - to_date(checkin_date)).days
        booking_result = update_hotel_booking_from_api(booking_id, to_date(checkin_date).isoformat(), to_date(checkout_date).isoformat(), total_price)
        if booking_result:
            return booking_result
        else:
            return f"Không tìm thấy mã đặt phòng {booking_id} để cập nhật."
    except Exception as e:
        return f"Đã xảy ra lỗi khi cập nhật: {e}"

@tool
def cancel_hotel_booking(
    booking_id: int,
) -> str:
    """
    Cancel a hotel booking based on booking id.
    """
    booking_info = fetch_booking_info_from_api(booking_id)
    if booking_info["status"] == "cancelled":
        return f"Không thể hủy mã đặt phòng {booking_id} vì đã bị hủy."
    try:
        booking_result = cancel_hotel_booking_from_api(booking_id)
        if booking_result:
            return f"Đã hủy thành công mã đặt phòng {booking_id}."
        else:
            return f"Không tìm thấy mã đặt phòng {booking_id} để hủy."
    except Exception as e:
        return f"Đã xảy ra lỗi khi hủy đặt phòng: {e}"