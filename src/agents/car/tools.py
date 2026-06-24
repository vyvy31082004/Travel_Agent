from datetime import date, datetime
from typing import Optional
from langchain_core.tools import tool

# Remove sqlite3 and direct file access
# import sqlite3 
from dotenv import load_dotenv
import os

# Import all necessary functions from the new api_client
from utils.api_client import (
    search_car_rentals_from_api,
    search_cars_from_api,
    book_car_rental_in_api,
    update_car_booking_in_api,
    cancel_car_booking_in_api,
    fetch_car_rental_info_from_api,
    fetch_car_info_from_api,
    fetch_car_booking_info_from_api,
    check_realse_car_from_api,
)

# Keep utility functions if they are still needed
from utils.utils import to_date

load_dotenv()

@tool
def search_car_rentals(
location: Optional[str] = None, 
name: Optional[str] = None, 
price_tier: Optional[str] = None,
rating: Optional[float] = None
) -> list[dict]:
    """Find car rentals based on location, name, rating, and price tier."""
    return search_car_rentals_from_api(location, name, price_tier, rating)

@tool
def search_cars(
rental_id: Optional[int] = None,
car_type: Optional[str] = None,
car_rental_name: Optional[str] = None,
price: Optional[int] = None,
capacity: Optional[int] = None,
) -> list[dict]:
    """Find cars based on rental id, car rental name, car type, capacity, and price."""
    # The rating parameter is removed as it's not available in the CAR_DETAILS data.
    return search_cars_from_api(
        rental_id=rental_id,
        car_type=car_type,
        car_rental_name=car_rental_name,
        price=price,
        capacity=capacity
    )

@tool
def book_car_rental(
rental_name: str,
car_name: str,
start_date: str,
end_date: str,
number_of_people: int,
) -> str:
    """
    Book a car rental. You must provide the rental name, car name, start date, end date, and number of people.
    First, find the rental_id and car_id, then check capacity and price before booking.
    """
    if not start_date or not end_date:
        return "Bạn cần cung cấp ngày nhận xe và ngày trả xe."
    if not number_of_people:
        return "Bạn cần cung cấp số lượng người."
    if not rental_name or not car_name:
        return "Bạn cần cung cấp tên đại lý cho thuê xe và tên xe."
    if to_date(start_date) > to_date(end_date):
        return "Ngày nhận xe phải trước ngày trả xe."
    if to_date(start_date) < date.today():
        return "Ngày nhận xe phải sau ngày hiện tại."
    if to_date(end_date) < date.today():
        return "Ngày trả xe phải sau ngày hiện tại."
    rental_id = fetch_car_rental_info_from_api(rental_name)
    if not rental_id:
        return f"Không tìm thấy đại lý cho thuê xe nào có tên '{rental_name}'."

    car_info = fetch_car_info_from_api(car_name, rental_id)
    if not car_info or not car_info["car_id"]:
        return f"Không tìm thấy xe '{car_name}' tại đại lý '{rental_name}'."
        
    car_id = car_info["car_id"]
    car_price_per_day = car_info["car_price"]
    car_capacity = car_info["car_capacity"]

    if number_of_people > car_capacity:
        return f"Xe chỉ có sức chứa {car_capacity} người. Không thể đặt cho {number_of_people} người."

    unavailable_car = check_realse_car_from_api("book", None, car_id, start_date, end_date)
    if unavailable_car:
        return f"Xe '{car_name}' tại đại lý '{rental_name}' đã được đặt trong khoảng thời gian '{start_date}' - '{end_date}'."
    try:
        start_dt = to_date(start_date)
        end_dt = to_date(end_date)
        num_days = (end_dt - start_dt).days
        if num_days <= 0:
            return "Ngày trả xe phải sau ngày nhận xe."
        total_price = car_price_per_day * num_days
    except Exception:
        total_price = car_price_per_day 

    try:
        booking_result = book_car_rental_in_api(
            rental_id=rental_id,
            car_id=car_id,
            start_date=start_date,
            end_date=end_date,
            number_of_people=number_of_people,
            total_price=total_price,
        )
        return f"Đặt xe thành công! Mã đặt xe của bạn là {booking_result.get('booking_id')}. Tổng chi phí là {total_price:,.0f} VNĐ."
    except Exception as e:
        return f"Đã xảy ra lỗi khi đặt xe: {e}"

@tool
def update_car_rental(
booking_id: int,
start_date: Optional[str] = None,
end_date: Optional[str] = None,
) -> str:
    """Update a car booking's start date or end date using the booking ID."""
    # if not start_date and not end_date:
    #     return "Bạn cần cung cấp ngày nhận xe hoặc ngày trả xe mới."

    # try:
    #     updated_booking = update_car_booking_in_api(booking_id, new_start_date=start_date, new_end_date=end_date)
    #     if updated_booking:
    #         return f"Cập nhật thành công cho mã đặt xe {booking_id}."
    #     else:
    #         return f"Không tìm thấy mã đặt xe {booking_id} để cập nhật."
    # except Exception as e:
    #     return f"Đã xảy ra lỗi khi cập nhật: {e}"
    if not start_date or not end_date:
        return "Bạn cần cung cấp ngày nhận xe và ngày trả xe."
    if to_date(start_date) > to_date(end_date):
        return "Ngày nhận xe phải trước ngày trả xe."
    if to_date(start_date) < date.today():
        return "Ngày nhận xe phải sau ngày hiện tại."
    if to_date(end_date) < date.today():
        return "Ngày trả xe phải sau ngày hiện tại."
    booking_status = fetch_car_booking_info_from_api(booking_id)["status"]
    if booking_status == "cancelled":
        return f"Không thể cập nhật mã đặt xe {booking_id} vì đã bị hủy."
    unavailable_car = check_realse_car_from_api("update", booking_id, None, start_date, end_date)
    if unavailable_car:
        return f"Xe đã được đặt trong khoảng thời gian '{start_date}' - '{end_date}'."
    try:
        car_id = fetch_car_booking_info_from_api(booking_id)["car_id"]
        car_info = fetch_car_info_from_api(None, None, car_id)
        car_price = car_info["car_price"]
        total_price = car_price * (to_date(end_date) - to_date(start_date)).days
        booking_result = update_car_booking_in_api(booking_id, to_date(start_date).isoformat(), to_date(end_date).isoformat(), total_price)
        if booking_result:
            return booking_result
        else:
            return f"Không tìm thấy mã đặt xe {booking_id} để cập nhật."
    except Exception as e:
        return f"Đã xảy ra lỗi khi cập nhật: {e}"

@tool
def cancel_car_rental(booking_id: int) -> str:
    """Cancel a car booking using its booking ID."""
    booking_info = fetch_car_booking_info_from_api(booking_id)
    if booking_info["status"] == "cancelled":
        return f"Không thể hủy mã đặt xe {booking_id} vì đã bị hủy."
    try:
        booking_result = cancel_car_booking_in_api(booking_id)
        if booking_result:
            return f"Đã hủy thành công mã đặt xe {booking_id}."
        else:
            return f"Không tìm thấy mã đặt xe {booking_id} để hủy."
    except Exception as e:
        return f"Đã xảy ra lỗi khi hủy đặt xe: {e}"  
