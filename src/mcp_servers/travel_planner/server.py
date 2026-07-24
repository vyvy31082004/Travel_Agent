from mcp.server.fastmcp import FastMCP
from mcp_servers.travel_planner.tools import register_travel_planner_tools

mcp = FastMCP(
    "travel-planner-server",
    host="127.0.0.1",
    port=8005,
)

register_travel_planner_tools(mcp)

if __name__ == "__main__":
    mcp.run(transport="sse")