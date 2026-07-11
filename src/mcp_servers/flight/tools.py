from typing import Optional

from services.flight_service import (
    search_one_way_flights,
    search_round_trip_flights,
    # get_booking_link_from_api 

)


def register_flight_tools(mcp):

    @mcp.tool()
    def search_one_way_flights_tool(
        origin: str,
        destination: str,
        departure_date: Optional[str] = None,
        adults: int = 1,
        children: int = 0,
        infant_on_lap: int = 0,
        infant_in_seat: int = 0,
        cabin_class: str = "economy",
        sort_by: str = "best",
        stops: str = "0",
        alliances: Optional[str] = None,
        airlines: Optional[str] = None,
        carry_on_bag: int = 0,
        max_price: Optional[int] = None,
        emissions: int = 0,
        layover_duration: Optional[str] = None,
        airports: Optional[str] = None,
        flight_duration: Optional[str] = None,
        preferred_departure_time: Optional[str] = None,
        preferred_arrival_time: Optional[str] = None,
        time_tolerance_minutes: int = 60,
        limit: int = 10,
    ) -> list[dict]:
        """
        Search one-way flights. Use when the user wants a single-direction trip only.

        stops: "0"=any, "1"=nonstop only, "2"=1 stop or fewer, "3"=2 stops or fewer.
        preferred_departure_time / preferred_arrival_time: "HH:MM" — filters within ±time_tolerance_minutes.

        When presenting results, include ALL fields for each flight and each segment:
        price, airline_code, airline_name, stops, duration_minutes,
        departure_time, departure_date, arrival_time, arrival_date,
        departure_airport_code, departure_airport_name,
        arrival_airport_code, arrival_airport_name,
        flight_number, aircraft, seat_pitch, overnight.
        """
        return search_one_way_flights(
            origin=origin,
            destination=destination,
            departure_date=departure_date,
            adults=adults,
            children=children,
            infant_on_lap=infant_on_lap,
            infant_in_seat=infant_in_seat,
            cabin_class=cabin_class,
            sort_by=sort_by,
            stops=stops,
            alliances=alliances,
            airlines=airlines,
            carry_on_bag=carry_on_bag,
            max_price=max_price,
            emissions=emissions,
            layover_duration=layover_duration,
            airports=airports,
            flight_duration=flight_duration,
            preferred_departure_time=preferred_departure_time,
            preferred_arrival_time=preferred_arrival_time,
            time_tolerance_minutes=time_tolerance_minutes,
            limit=limit,
        )

    @mcp.tool()
    def search_round_trip_flights_tool(
        origin: str,
        destination: str,
        departure_date: Optional[str] = None,
        return_date: Optional[str] = None,
        adults: int = 1,
        children: int = 0,
        infant_on_lap: int = 0,
        infant_in_seat: int = 0,
        cabin_class: str = "economy",
        sort_by: str = "best",
        stops: str = "0",
        alliances: Optional[str] = None,
        airlines: Optional[str] = None,
        carry_on_bag: int = 0,
        max_price: Optional[int] = None,
        emissions: int = 0,
        layover_duration: Optional[str] = None,
        airports: Optional[str] = None,
        flight_duration: Optional[str] = None,
        preferred_departure_time: Optional[str] = None,
        preferred_arrival_time: Optional[str] = None,
        preferred_return_departure_time: Optional[str] = None,
        preferred_return_arrival_time: Optional[str] = None,
        time_tolerance_minutes: int = 60,
        limit: int = 2,
    ) -> list[dict]:
        """
        Search roundtrip flights. Use when the user wants to fly out AND return.
        Returns paired results: each outbound flight includes 'inbound_options' — the list
        of available return flights for that specific outbound leg.

        stops: "0"=any, "1"=nonstop only, "2"=1 stop or fewer, "3"=2 stops or fewer.
        preferred_departure_time / preferred_arrival_time: "HH:MM" — filters outbound leg within ±time_tolerance_minutes.
        preferred_return_departure_time / preferred_return_arrival_time: "HH:MM" — filters inbound (return) leg.

        When presenting results, for EACH pair show:
        - Outbound: price, airline_code, airline_name, departure_time, departure_date,
          arrival_time, arrival_date, departure_airport_code, arrival_airport_code,
          flight_number, aircraft, stops, duration_minutes.
        - inbound_options[]: same fields for each available return flight.
        """
        return search_round_trip_flights(
            origin=origin,
            destination=destination,
            departure_date=departure_date,
            return_date=return_date,
            adults=adults,
            children=children,
            infant_on_lap=infant_on_lap,
            infant_in_seat=infant_in_seat,
            cabin_class=cabin_class,
            sort_by=sort_by,
            stops=stops,
            alliances=alliances,
            airlines=airlines,
            carry_on_bag=carry_on_bag,
            max_price=max_price,
            emissions=emissions,
            layover_duration=layover_duration,
            airports=airports,
            flight_duration=flight_duration,
            preferred_departure_time=preferred_departure_time,
            preferred_arrival_time=preferred_arrival_time,
            preferred_return_departure_time=preferred_return_departure_time,
            preferred_return_arrival_time=preferred_return_arrival_time,
            time_tolerance_minutes=time_tolerance_minutes,
            limit=limit,
        )
    # @mcp.tool()
    # def book_flight_by_id_tool(
    #     flight_id: str,
    #     cabin_class: str = "economy",
    #     adults: int = 1,
    #     children: int = 0,
    #     infant_on_lap: int = 0,
    #     infant_in_seat: int = 0,
    # ) -> dict:
    #     """
    #     Book a flight by its flight_id.
    #     """
    #     return get_booking_link_from_api(
    #         flight_id=flight_id,
    #         cabin_class=cabin_class,
    #         adults=adults,
    #         children=children,
    #         infant_on_lap=infant_on_lap,
    #         infant_in_seat=infant_in_seat,
    #     )

