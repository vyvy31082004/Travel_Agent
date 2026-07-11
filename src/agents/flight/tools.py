from langchain_mcp_adapters.client import MultiServerMCPClient


async def get_flight_tools():
    client = MultiServerMCPClient(
        {
            "flight": {
                "url": "http://127.0.0.1:8000/sse",
                "transport": "sse",
            }
        }
    )
    tools = await client.get_tools()
    flight_tool_names = {
        "search_one_way_flights_tool",
        "search_round_trip_flights_tool",
    }
    return [tool for tool in tools if tool.name in flight_tool_names]
