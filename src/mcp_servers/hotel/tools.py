from typing import Optional

from services.hotel_service import (
    search_hotels,
    get_hotel_room_list,
    # search_hotel_rooms,
    # book_hotel_room,
    # cancel_hotel_booking,
)


def register_hotel_tools(mcp):
    @mcp.tool()
    def search_hotels_tool(
            location: str | None = None,
            name: str | None = None,
            price_tier: str | None = None,
            price: int | None = None,
            rating: float | None = None,
            checkin_date: str | None = None,
            checkout_date: str | None = None,
            adults: int = 2,
            children_age: str | None = None,
            room_qty: int = 1,
            price_min: int | None = None,
            price_max: int | None = None,
            limit: int = 10,
    ) -> list[dict]:
        """
        Search hotels by location/name, dates, adults, children_age,price, price tier, price_min, price_max, and room quantity. 
        When calling search_hotels_tool, if user mentions ANY child age, you MUST pass children_age.
        - This applies to ALL ages 0-18, including 16 and 17. Never omit children_age for teenagers.\n"
        - "X người lớn" -> adults=X
        - "Y trẻ em Z tuổi" -> children_age="Z"  (one age per child, comma-separated string)
        - Multiple children: "1 trẻ 8 tháng và 1 trẻ 16 tuổi" -> children_age="0,16"
        Examples:
        - "2 người lớn, 1 trẻ em 16 tuổi" -> adults=2, children_age="16"
        - "2 adults, 1 child age 16" -> adults=2, children_age="16"
        - "2 trẻ: 1 tuổi và 17 tuổi" -> children_age="1,17"
        - Children age is from 0-18 years old.
        - children_age must be a comma-separated string of ages, not a count of children.
        - Infants under 1 year old use age 0.
        """
        return search_hotels(
            location=location,
            name=name,
            price_tier=price_tier,
            price = price,
            rating=rating,
            checkin_date=checkin_date,
            checkout_date=checkout_date,
            adults=adults,
            children_age=children_age,
            price_min=price_min,
            price_max=price_max,
            room_qty=room_qty,
            limit=limit,
        )
    @mcp.tool()
    def get_hotel_room_list_tool(
        hotel_id: str,
        checkin_date: str,
        checkout_date: str,
        adults: int = 2,
        children_age: str | None = None,
        room_qty: int = 1,
        price: int | None = None,
        price_min: int | None = None,
        price_max: int | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """
        Get available room types/rates for ONE hotel via Booking getRoomList.
        REQUIRED:
        - hotel_id: external_hotel_id from search_hotels_tool (NOT the MCP message id like lc_xxx)
        - checkin_date / checkout_date: YYYY-MM-DD or DD/MM/YYYY
        GUESTS:
        - "X người lớn" -> adults=X
        - "Y trẻ em Z tuổi" -> children_age="Z"
        - Multiple children: "1 trẻ 5 tuổi và 1 trẻ 16 tuổi" -> children_age="5,16"
        PRICE:
        - "giá cao nhất 2 triệu" -> price_max=2000000
        - Use price_max/price_min, NOT price_tier
        Example flow:
        1. search_hotels_tool(location="Nha Trang", ...)
        2. get_hotel_room_list_tool(hotel_id="16256042", checkin_date="2026-09-20", checkout_date="2026-09-22", adults=2, children_age="5")
        """
        return get_hotel_room_list(
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

    # @mcp.tool()
    # def search_hotel_rooms_tool(
    #     hotel_name: Optional[str] = None,
    #     room_type: Optional[str] = None,
    #     price: Optional[int] = None,
    #     price_max: Optional[int] = None,
    #     price_min: Optional[int] = None,
    #     capacity: Optional[int] = None,
    # ):
    #     """Search hotel rooms by hotel name, room type, price and capacity."""
    #     return search_hotel_rooms(
    #         hotel_name=hotel_name,
    #         room_type=room_type,
    #         price=price,
    #         price_max=price_max,
    #         price_min=price_min,
    #         capacity=capacity,
    #     )

    # @mcp.tool()
    # def book_hotel_room_tool(
    #     room_id: int,
    #     hotel_id: int,
    #     checkin_date: str,
    #     checkout_date: str,
    #     total_price: int,
    # ) -> dict:
    #     """Book a hotel room."""
    #     return book_hotel_room(
    #         room_id=room_id,
    #         hotel_id=hotel_id,
    #         checkin_date=checkin_date,
    #         checkout_date=checkout_date,
    #         total_price=total_price,
    #     )

    # @mcp.tool()
    # def cancel_hotel_booking_tool(booking_id: int):
    #     """Cancel hotel booking by booking_id."""
    #     return cancel_hotel_booking(booking_id)