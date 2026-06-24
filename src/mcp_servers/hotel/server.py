# # src/mcp_servers/hotel/server.py
# from mcp.server.fastmcp import FastMCP
# from mcp_servers.hotel.tools import register_hotel_tools

# mcp = FastMCP("hotel-server")
# register_hotel_tools(mcp)

# if __name__ == "__main__":
#     # Chạy server bằng SSE trên port 8000 thay vì stdio
#     mcp.run(transport="sse", port=8000) 

# src/mcp_servers/hotel/server.py
from mcp.server.fastmcp import FastMCP
from mcp_servers.hotel.tools import register_hotel_tools

mcp = FastMCP(
    "hotel-server",
    host="127.0.0.1",
    port=8000,
)

register_hotel_tools(mcp)

if __name__ == "__main__":
    mcp.run(transport="sse")