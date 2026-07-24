from typing import Optional

from services.travel_planner_service import (
    get_weather,
)


def register_travel_planner_tools(mcp):
    @mcp.tool()
    def get_weather_tool(
        location: str,
        days: int = 3,
    ) -> dict:
        if not location:
            return {"error": "Location is required"}
        return get_weather(location, days)