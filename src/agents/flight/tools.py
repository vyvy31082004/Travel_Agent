from langchain_core.tools import tool
from typing import Optional
from datetime import datetime
from langchain_core.runnables import RunnableConfig
from utils.api_client_flight import (
    search_flights_from_api
)
from utils.utils import to_date


# @tool
# def search_flights(
#     departure_airport_code: Optional[str] = None,
#     arrival_airport_code: Optional[str] = None,
#     departure_time: Optional[str] = None,
#     arrival_time: Optional[str] = None,
#     city_depart: Optional[str] = None,
#     city_arrive: Optional[str] = None,
#     flight_no: Optional[str] = None,
# ) -> list[dict]:
#     """
#     Search for flights based on departure airport name or code, arrival airport name or code, and date.
#     """
#     if not (departure_airport_code or arrival_airport_code or city_depart or city_arrive or flight_no or departure_time or arrival_time):
#         return "Please provide either departure airport name or code, arrival airport name or code, city depart, city arrive, flight no, departure time, arrival time."
#     return search_flight_from_api(
#         departure_airport_code=departure_airport_code,
#         arrival_airport_code=arrival_airport_code,
#         departure_time=departure_time,
#         arrival_time=arrival_time,
#         city_depart=city_depart,
#         city_arrive=city_arrive,
#         flight_no=flight_no,
#     )


@tool
def search_flight(
    origin: str,
    destination: str,
    departure_date: Optional[str] = None,
    return_date: Optional[str] = None,
    trip_type: str = "one_way",
    adults: int = 1,
    children: int = 0,
    infants: int = 0,
    cabin_class: str = "economy",
    sort_by: str = "best",
    page: int = 1,
    limit: int = 5,
) -> list[dict]:
    """
    Search flights by origin, destination, and travel date.

    Use this tool when the user wants to find flights.

    Important:
    - departure_date is required for flight search.
    - Do not invent a date if the user does not provide one.
    - If the user does not provide a date, ask for the departure date.
    - return_date is required only for round_trip.
    - The returned flight results may include detail_token.
    - detail_token is used internally by get_flight_details.
    - Do not ask the user to provide token/detail_token.
    """

    return search_flights_from_api(
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        return_date=return_date,
        trip_type=trip_type,
        adults=adults,
        children=children,
        infants=infants,
        cabin_class=cabin_class,
        sort_by=sort_by,
        page=page,
        limit=limit,
    )

# @tool
# def search_flight_price(
#     flight_id: str | None = None,
#     seat_type: str | None = None,
# ) -> float:
#     """
#     Search for flight prices based on flight_id and seat_type. if seat_type is not provided, return all seat types prices.
#     """
#     if not flight_id:
#         return "Please provide a flight_id."
#     return search_flight_price_from_api(flight_id=flight_id, seat_type=seat_type)


# # def fetch_user_flight_information(config: RunnableConfig) -> list[dict]:
# #     """Fetch all tickets for the user along with corresponding flight information and seat assignments.

# #     Returns:
# #         A list of dictionaries where each dictionary contains the ticket details,
# #         associated flight details, and the seat assignments for each ticket belonging to the user.
# #     """
# #     configuration = config.get("configurable", {})
# #     passenger_id = configuration.get("passenger_id", None)
# #     if not passenger_id:
# #         raise ValueError("No passenger ID configured.")
        
# #     return fetch_user_flight_information_from_api(passenger_id)

# @tool
# def book_flight(
#     seat_type: str,
#     num_passenger: int,
#     flight_id: str = None
# ) -> str:
#     """
#     Book flight based on flight_id, seat_type and number of passengers.
#     After booking, you should ask the user for passenger details for each ticket.
#     """
#     if not flight_id :
#         return "Please provide a flight_id."
    
#     return book_flight_from_api(
#         flight_id=flight_id,
#         seat_type=seat_type,
#         passengers=num_passenger
#     )

# @tool
# def provide_passenger_details(
#     ticket_no: str,
#     passenger_name: str = None,
#     date_of_birth: str = None,
#     id_type: str = None,
#     id_number: str = None,
#     nationality: str = None
# ) -> str:
#     """
#     Provide passenger details for a specific ticket number.
#     Can be called multiple times to update information for different tickets.
    
#     Args:
#         ticket_no: The ticket number to update (e.g., "T004", "T005")
#         passenger_name: Full name of the passenger
#         date_of_birth: Date of birth (format: YYYY-MM-DD or DD/MM/YYYY)
#         id_type: Type of ID document (CMND, CCCD, Passport, etc.)
#         id_number: ID document number
#         nationality: Passenger's nationality
#         contact_email: Contact email (optional)
#         contact_phone: Contact phone (optional)
    
#     Example workflow:
#         After booking creates tickets T004, T005, T006...
        
#         User says: "Ticket T004: Nguyễn Văn A, CMND 123456789, sinh ngày 15/05/1990
#                     Ticket T005: Trần Thị B, CCCD 987654321, sinh ngày 20/03/1995"
        
#         AI automatically parses and calls:
#         1. provide_passenger_details(
#                passenger_name="Nguyễn Văn A", 
#                id_type="CMND", 
#                id_number="123456789",
#                date_of_birth="1990-05-15"
#            )
#         2. provide_passenger_details(
#                passenger_name="Trần Thị B",
#                id_type="CCCD", 
#                id_number="987654321",
#                date_of_birth="1995-03-20"
#            )
    
#     Note: The AI can understand natural language and extract structured data automatically.
#     Users don't need to format their input - they can speak naturally!
#     """
#     if not ticket_no:
#         return "Please provide a ticket_no."
#     return update_ticket_passenger_from_api(
#         ticket_no=ticket_no,
#         passenger_name=passenger_name,
#         date_of_birth=date_of_birth,
#         id_type=id_type,
#         id_number=id_number,
#         nationality=nationality,
#     )


# @tool
# def get_booking_tickets(booking_id: str) -> str:
#     """
#     Get all ticket numbers for a specific booking and their passenger assignment status.
#     Use this to check which tickets need passenger information.
   
#     Returns: List of ticket numbers and their current passenger assignment status
#     """
#     from utils.api_client_flight import _load_data
   
#     if not booking_id:
#         return "Please provide a booking_id."
   
#     data = _load_data()
#     tickets = data.get("tickets", [])
   
#     booking_tickets = [t for t in tickets if t.get("booking_id") == booking_id]
   
#     if not booking_tickets:
#         return f"No tickets found for booking {booking_id}."
   
#     ticket_list = []
#     for t in booking_tickets:
#         ticket_id = t.get('ticket_id') or t.get('ticket_no')
#         if t.get('passenger_name'):
#             status = f" Assigned to: {t.get('passenger_name')}"
#         else:
#             status = "Passenger details needed"
#         ticket_list.append(f"  • {ticket_id}: {status}")
   
#     return f"Booking {booking_id} has {len(booking_tickets)} ticket(s):\n" + "\n".join(ticket_list)


# @tool
# def batch_update_passengers(
#     booking_id: str,
#     passengers_info: list[dict]
# ) -> str:
#     """
#     Update multiple tickets with passenger information at once.
#     Useful when user provides all passenger details together.
    
#     Args:
#         booking_id: The booking ID
#         passengers_info: List of passenger information dictionaries.
#                         Each dict should contain: full_name, dob, id_type, id_number, nationality
    
#     Example:
#         User: "Booking BKG005, người thứ nhất: Nguyễn Văn A, CMND 123456789, sinh 15/5/1990
#                người thứ hai: Trần Thị B, CCCD 987654321, sinh 20/3/1995"
        
#         AI extracts and calls:
#         batch_update_passengers(
#             booking_id="BKG005",
#             passengers_info=[
#                 {
#                     "full_name": "Nguyễn Văn A",
#                     "id_type": "CMND",
#                     "id_number": "123456789",
#                     "dob": "1990-05-15",
#                     "nationality": "Vietnam"
#                 },
#                 {
#                     "full_name": "Trần Thị B", 
#                     "id_type": "CCCD",
#                     "id_number": "987654321",
#                     "dob": "1995-03-20",
#                     "nationality": "Vietnam"
#                 }
#             ]
#         )
#     """
#     return update_multiple_tickets_with_passengers(
#         booking_id=booking_id,
#         passengers_info=passengers_info
#     )

# @tool
# def cancel_booking(booking_id: str) -> str:
#     """
#     Cancel a booking.
#     """
#     return cancel_booking_from_api(booking_id=booking_id)
