from mcp.server.fastmcp import FastMCP
from mcp_servers.flight.tools import register_flight_tools

mcp = FastMCP(
    "flight-server",
    host="127.0.0.1",
    port=8000,
)

register_flight_tools(mcp)

if __name__ == "__main__":
    mcp.run(transport="sse")