import sqlite3
from langchain_core.tools import tool
from typing import Optional
from utils.constant import RANGE_PRICE_TRIP
from dotenv import load_dotenv
from datetime import date, datetime
from utils.utils import to_date
load_dotenv()

from langchain_mcp_adapters.client import MultiServerMCPClient
from langsmith import traceable

@traceable(run_type="chain", name="load_car_mcp_tools")
async def get_car_tools():
    client = MultiServerMCPClient(
        {
            "car": {
                "url": "http://127.0.0.1:8001/sse",
                "transport": "sse",
            }
        }
    )
    tools = await client.get_tools()
    car_tool_names = {
        "search_cars_tool",
        "get_car_details_tool",
    }
    return [tool for tool in tools if tool.name in car_tool_names]