from langchain_core.tools import tool
from typing import Optional
from datetime import datetime
from langchain_core.runnables import RunnableConfig
from utils.api_client_flight import (
    search_flight_from_api, 
    search_flight_price_from_api, 
    fetch_user_flight_information_from_api,
    book_flight_from_api,
    update_ticket_passenger_from_api
)
from utils.utils import to_date


@tool
def search_flights(
    departure_airport_code: Optional[str] = None,
    arrival_airport_code: Optional[str] = None,
    departure_time: Optional[str] = None,
    arrival_time: Optional[str] = None,
    city_depart: Optional[str] = None,
    city_arrive: Optional[str] = None,
    flight_no: Optional[str] = None,
) -> list[dict]:
    """
    Search for flights based on departure airport name or code, arrival airport name or code, and date.
    """
    if not (departure_airport_code or arrival_airport_code or city_depart or city_arrive or flight_no or departure_time or arrival_time):
        return "Please provide either departure airport name or code, arrival airport name or code, city depart, city arrive, flight no, departure time, arrival time."
    return search_flight_from_api(
        departure_airport_code=departure_airport_code,
        arrival_airport_code=arrival_airport_code,
        departure_time=departure_time,
        arrival_time=arrival_time,
        city_depart=city_depart,
        city_arrive=city_arrive,
        flight_no=flight_no,
    )


@tool
def search_flight_price(
    flight_id: str | None = None,
    seat_type: str | None = None,
) -> float:
    """
    Search for flight prices based on flight_id and seat_type. if seat_type is not provided, return all seat types prices.
    If passenger is not provided, return the price for 1 passenger.
    """
    if not flight_id:
        return "Please provide a flight_id."
    if not seat_type:
        return "Please provide a seat_type."
    return search_flight_price_from_api(flight_id=flight_id, seat_type=seat_type)


def fetch_user_flight_information(config: RunnableConfig) -> list[dict]:
    """Fetch all tickets for the user along with corresponding flight information and seat assignments.

    Returns:
        A list of dictionaries where each dictionary contains the ticket details,
        associated flight details, and the seat assignments for each ticket belonging to the user.
    """
    configuration = config.get("configurable", {})
    passenger_id = configuration.get("passenger_id", None)
    if not passenger_id:
        raise ValueError("No passenger ID configured.")
        
    return fetch_user_flight_information_from_api(passenger_id)

@tool
def book_flight(
    flight_id: str,
    seat_type: str,
    num_tickets: int,
) -> str:
    """
    Book a flight for multiple passengers. This will:
    1. Create a booking with the specified number of tickets
    2. Generate ticket IDs (e.g., T001, T002, T003) for each passenger
    3. Each ticket will have passenger_id=None initially

    After booking, you MUST ask the user for passenger details for each ticket
    using the provide_passenger_details tool.

    Args:
        flight_id: The flight ID to book
        seat_type: Seat type (eco, business, first)
        num_tickets: Number of tickets/passengers

    Returns:
        Booking confirmation with booking_id and list of ticket_ids
    """
    return book_flight_from_api(
        flight_id=flight_id,
        seat_type=seat_type,
        num_tickets=num_tickets
    )

@tool
def provide_passenger_details(
    ticket_id: str,
    full_name: str,
    dob: str,
    id_type: str,
    id_number: str,
    nationality: str,
) -> str:
    """
    Provide passenger details for a specific ticket.

    This tool will:
    1. Check if passenger already exists (by id_type + id_number)
    2. If passenger exists, use existing passenger_id
    3. If passenger doesn't exist, create new passenger in database
    4. Update the ticket's passenger_id

    Args:
        ticket_id: The ticket ID (e.g., T001, T002)
        full_name: Full name of the passenger (e.g., "Nguyễn Văn An")
        dob: Date of birth (e.g., "1990-05-12")
        id_type: Type of ID document (e.g., "CCCD", "Passport")
        id_number: ID document number (e.g., "079123456789")
        nationality: Nationality (e.g., "Vietnam")

    Returns:
        Confirmation message with passenger assignment status
    """
    if not ticket_id:
        return "Please provide a ticket_id."
    if not full_name:
        return "Please provide full_name."
    if not dob:
        return "Please provide dob (date of birth)."
    if not id_type:
        return "Please provide id_type (e.g., CCCD, Passport)."
    if not id_number:
        return "Please provide id_number."
    if not nationality:
        return "Please provide nationality."

    return update_ticket_passenger_from_api(
        ticket_id=ticket_id,
        full_name=full_name,
        dob=dob,
        id_type=id_type,
        id_number=id_number,
        nationality=nationality
    )


