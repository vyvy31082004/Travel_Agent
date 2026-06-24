# # src/mcp_clients/client.py

# from functools import lru_cache
# from typing import Any

# from langchain_mcp_adapters.client import MultiServerMCPClient


# @lru_cache(maxsize=1)
# def get_mcp_client() -> MultiServerMCPClient:
#     return MultiServerMCPClient(
#         {
#             "hotel": {
#                 "command": "python",
#                 "args": ["-m", "mcp_servers.hotel.server"],
#                 "transport": "stdio",
#             }
#         }
#     )


# async def call_mcp_tool(tool_name: str, arguments: dict[str, Any]) -> Any:
#     client = get_mcp_client()
#     tools = await client.get_tools()

#     tool_map = {tool.name: tool for tool in tools}

#     if tool_name not in tool_map:
#         available = ", ".join(tool_map.keys())
#         raise ValueError(
#             f"MCP tool '{tool_name}' not found. Available tools: {available}"
#         )

#     return await tool_map[tool_name].ainvoke(arguments)