from mcp.server.fastmcp import FastMCP
from mcp_servers.excursion.tools import register_excursion_tools

mcp = FastMCP(
    "excursion-server",
    host="127.0.0.1",
    port=8000,
)

register_excursion_tools(mcp)

if __name__ == "__main__":
    mcp.run(transport="sse")