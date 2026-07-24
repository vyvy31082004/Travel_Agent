from langchain_mcp_adapters.client import MultiServerMCPClient
from langsmith import traceable


@traceable(run_type="chain", name="load_travel_planner_mcp_tools")
async def get_travel_planner_tools():
    client = MultiServerMCPClient(
        {
            "car": {
                "url": "http://127.0.0.1:8001/sse",
                "transport": "sse",
            },
            "excursion": {
                "url": "http://127.0.0.1:8002/sse",
                "transport": "sse",
            },
            "flight": {
                "url": "http://127.0.0.1:8003/sse",
                "transport": "sse",
            },
            "hotel": {
                "url": "http://127.0.0.1:8004/sse",
                "transport": "sse",
            },
            "travel_planner": {
                "url": "http://127.0.0.1:8005/sse",
                "transport": "sse",
            }
        }
    )
    tools = await client.get_tools()
    travel_planner_tool_names = {
        "search_cars_tool",
        "get_car_details_tool",
        "search_attractions_tool",
        "fetch_attraction_details_tool",
        "fetch_attraction_reviews_tool",
        "search_one_way_flights_tool",
        "search_round_trip_flights_tool",
        "search_hotels_tool",
        "get_hotel_room_list_tool",
        "get_hotel_reviews_tool",
        "get_hotel_facility_tool",
        "get_hotel_policy_tool",
        "get_weather_tool",
    }
    return [tool for tool in tools if tool.name in travel_planner_tool_names]