from typing import Optional

from utils.api_client_planner import (
    get_weather_from_api,
)

def get_weather(
    location: str,
    days: int = 3,
) -> dict:
    return get_weather_from_api(location, days)