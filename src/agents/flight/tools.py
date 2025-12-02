from langchain_core.tools import tool
from typing import Optional
from datetime import datetime
from utils.api_client_flight import search_flight_from_api, _load_data
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
def fetch_user_flight_information() -> list[dict]:
    """Fetch all flights for the current user."""
    _load_data()
    return [] # Placeholder


