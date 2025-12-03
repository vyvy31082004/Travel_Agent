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
    Book a flight. This will generate the booking and tickets.
    Returns the booking ID and list of generated ticket numbers.
    After booking, you should ask the user for passenger details for each ticket using update_ticket_passenger.
    """
    return book_flight_from_api(
        flight_id=flight_id,
        seat_type=seat_type,
        passengers=num_tickets
    )

@tool
def provide_passenger_details(
    ticket_id: str,
    passenger_name: str,
    date_of_birth: str,
    id_type: str,
    id_number: str,
    nationality: str,
) -> str:
    """
    Provide passenger details for a specific ticket.
    """
    if not ticket_id:
        return "Please provide a ticket_id."
    if not passenger_name:
        return "Please provide a passenger_name."
    if not date_of_birth:
        return "Please provide a date_of_birth."
    if not id_type:
        return "Please provide a id_type."
    if not id_number:
        return "Please provide a id_number."
    if not nationality:
        return "Please provide a nationality."
    return update_ticket_passenger_from_api(
        ticket_id=ticket_id,
        passenger_name=passenger_name,
        date_of_birth=date_of_birth,
        id_type=id_type,
        id_number=id_number,
        nationality=nationality
    )


