from mcp.server.fastmcp import FastMCP
from mcp_servers.car.tools import register_car_tools

mcp = FastMCP(
    "car-server",
    host="127.0.0.1",
    port=8001,
)

register_car_tools(mcp)

if __name__ == "__main__":
    mcp.run(transport="sse")