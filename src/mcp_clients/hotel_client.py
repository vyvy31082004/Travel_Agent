# # src/mcp_clients/hotel_client.py

# from typing import Optional

# from mcp_clients.client import call_mcp_tool


# async def call_search_hotels(
#     location: Optional[str] = None,
#     name: Optional[str] = None,
#     price_tier: Optional[str] = None,
#     price: Optional[int] = None,
#     rating: Optional[float] = None,
#     checkin_date: Optional[str] = None,
#     checkout_date: Optional[str] = None,
#     adults: int = 2,
#     children_age: Optional[str] = None,
#     room_qty: int = 1,  
#     price_min: int | None = None,
#     price_max: int | None = None,
#     limit: int = 10,
# ):
#     return await call_mcp_tool(
#         "search_hotels_tool",
#         {
#             "location": location,
#             "name": name,
#             "price_tier": price_tier,
#             "price": price,
#             "rating": rating,
#             "checkin_date": checkin_date,
#             "checkout_date": checkout_date,
#             "adults": adults,
#             "children_age": children_age,
#             "room_qty": room_qty,
#             "price": price,
#             "price_min": price_min,
#             "price_max": price_max,
#             "limit": limit,
#         },
#     )

# async def call_get_hotel_room_list(
#     hotel_id: str,
#     checkin_date: str,
#     checkout_date: str,
#     adults: int = 2,
#     children_age: str | None = None,
#     room_qty: int = 1,
#     price: int | None = None,
#     price_min: int | None = None,
#     price_max: int | None = None,
#     limit: int = 20,
# ):
#     return await call_mcp_tool(
#         "get_hotel_room_list_tool",
#         {
#             "hotel_id": hotel_id,
#             "checkin_date": checkin_date,
#             "checkout_date": checkout_date,
#             "adults": adults,
#             "children_age": children_age,
#             "room_qty": room_qty,
#             "price": price,
#             "price_min": price_min,
#             "price_max": price_max,
#             "limit": limit,
#         },
#     )
# # async def call_search_hotel_rooms(**kwargs):
# #     return await call_mcp_tool("search_hotel_rooms_tool", kwargs)


# # async def call_book_hotel_room(**kwargs):
# #     return await call_mcp_tool("book_hotel_room_tool", kwargs)


# # async def call_cancel_hotel_booking(booking_id: int):
# #     return await call_mcp_tool(
# #         "cancel_hotel_booking_tool",
# #         {"booking_id": booking_id},
# #     )