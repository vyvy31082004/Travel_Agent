import json
from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, StateGraph
from langgraph.prebuilt import InjectedState, ToolNode, tools_condition
from dotenv import load_dotenv

from agents.flight.state import State
from agents.flight.tools import get_flight_tools
from prompts.prompt import flight_prompts
from utils.api_client_flight import get_booking_link_from_api
from utils.tracing import with_trace_config

load_dotenv()

_SEARCH_TOOL_NAMES = {
    "search_one_way_flights_tool",
    "search_round_trip_flights_tool",
}

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.2,
)


def _extract_token_map(messages: list) -> dict[str, str]:
    """Scan ToolMessages từ search tools, trả về mapping flight_id -> detailToken."""
    token_map: dict[str, str] = {}
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        if msg.name not in _SEARCH_TOOL_NAMES:
            continue
        try:
            content = msg.content
            parsed_items = []
            if isinstance(content, str):
                parsed_items.append(json.loads(content))
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parsed_items.append(json.loads(block["text"]))
                    else:
                        parsed_items.append(block)
            else:
                parsed_items.append(content)

            # Flatten if parsed_items contains lists
            items = []
            for pi in parsed_items:
                if isinstance(pi, list):
                    items.extend(pi)
                else:
                    items.append(pi)

            for item in items:
                if not isinstance(item, dict):
                    continue
                # Xử lý topFlights và otherFlights
                for flight_list_name in ["topFlights", "otherFlights"]:
                    flight_list = item.get(flight_list_name, [])
                    for flight in flight_list:
                        fid = flight.get("Offer_ID") or flight.get("flight_id")
                        token = flight.get("detailToken")
                        if fid and token:
                            token_map[fid] = token
                        
                        # Fallback: Xử lý khứ hồi (roundtrip) nếu Offer_ID nằm trong inbound (cũ)
                        if "inbound" in flight:
                            fid_inbound = flight["inbound"].get("Offer_ID") or flight["inbound"].get("flight_id")
                            if fid_inbound and token:
                                token_map[fid_inbound] = token
        except Exception:
            pass
    return token_map


def _strip_tokens_from_messages(messages: list) -> list:
    """Tạo bản sao ToolMessages từ search tools với detailToken/returningToken đã bị xóa."""
    cleaned: list = []
    for msg in messages:
        if not isinstance(msg, ToolMessage) or msg.name not in _SEARCH_TOOL_NAMES:
            cleaned.append(msg)
            continue
        try:
            content = msg.content
            is_mcp_format = False
            parsed_blocks = []

            if isinstance(content, str):
                parsed_blocks.append(json.loads(content))
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        is_mcp_format = True
                        parsed_blocks.append(json.loads(block["text"]))
                    else:
                        parsed_blocks.append(block)
            else:
                parsed_blocks.append(content)

            for parsed in parsed_blocks:
                items = parsed if isinstance(parsed, list) else [parsed]
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    
                    # Xóa token trong topFlights và otherFlights
                    for flight_list_name in ["topFlights", "otherFlights"]:
                        flight_list = item.get(flight_list_name, [])
                        for flight in flight_list:
                            if isinstance(flight, dict):
                                flight.pop("detailToken", None)
                                flight.pop("returningToken", None)
                            if "inbound" in flight and isinstance(flight["inbound"], dict):
                                flight["inbound"].pop("detailToken", None)
                                flight["inbound"].pop("returningToken", None)

            if is_mcp_format:
                new_content = []
                for i, block in enumerate(content):
                    if isinstance(block, dict) and block.get("type") == "text":
                        new_content.append({
                            "type": "text",
                            "text": json.dumps(parsed_blocks[i], ensure_ascii=False)
                        })
                    else:
                        new_content.append(block)
                final_content = new_content
            else:
                final_content = json.dumps(parsed_blocks[0], ensure_ascii=False)

            cleaned.append(
                ToolMessage(
                    content=final_content,
                    tool_call_id=msg.tool_call_id,
                    name=msg.name,
                )
            )
        except Exception:
            cleaned.append(msg)
    return cleaned


@tool
async def book_flight_by_id(
    flight_id: str,
    state: Annotated[dict, InjectedState],
    adults: int = 1,
    children: int = 0,
    infant_on_lap: int = 0,
    infant_in_seat: int = 0,
    cabin_class: str = "economy",
) -> dict:
    """
    Book a flight using the Offer_ID or flight_id displayed in search results (e.g. FL-A8B2C).
    Use this whenever the user wants to book a specific flight by its Offer_ID.
    The detailToken is resolved automatically from the session checkpointer.

    cabin_class values: 'economy', 'business', 'first', 'premium_economy'.
    """
    token_map: dict[str, str] = state.get("flight_token_map") or {}
    detail_token = token_map.get(flight_id)
    if not detail_token:
        return {
            "error": (
                f"Không tìm thấy flight_id '{flight_id}' trong phiên này. "
                "Vui lòng tìm kiếm chuyến bay trước rồi thử lại."
            )
        }
    return get_booking_link_from_api(
        detailToken=detail_token,
        adults=adults,
        children=children,
        infantsOnLap=infant_on_lap,
        infantsInSeat=infant_in_seat,
        cabinClass=cabin_class,
    )


async def build_flight_graph():
    mcp_tools = await get_flight_tools()
    # Loại bỏ book_flight từ MCP (thay bằng book_flight_by_id local)
    mcp_tools = [t for t in mcp_tools if t.name != "book_flight"]

    all_tools = mcp_tools + [book_flight_by_id]

    flight_runnable = (flight_prompts | llm.bind_tools(all_tools)).with_config(
        with_trace_config(
            run_name="flight_llm",
            tags=["customer-support", "flight", "llm"],
            metadata={"agent": "flight"},
        )
    )
    tool_node = ToolNode(all_tools).with_config(
        with_trace_config(
            run_name="flight_tools",
            tags=["customer-support", "flight", "tools", "mcp"],
            metadata={"agent": "flight", "tool_transport": "mcp_sse"},
        )
    )

    async def flight_chat(state: dict, config: RunnableConfig):
        messages = state.get("messages", [])

        # 1. Extract token mapping từ tất cả ToolMessages trong state
        new_token_map = _extract_token_map(messages)

        # 2. Tạo bản sao messages đã strip detailToken/returningToken để LLM không thấy
        cleaned_messages = _strip_tokens_from_messages(messages)
        cleaned_state = {**state, "messages": cleaned_messages}

        response = await flight_runnable.ainvoke(
            cleaned_state,
            config=with_trace_config(
                config,
                run_name="flight_chat",
                tags=["customer-support", "flight"],
                metadata={"agent": "flight"},
            ),
        )
        result: dict = {"messages": [response] if not isinstance(response, list) else response}
        if new_token_map:
            result["flight_token_map"] = new_token_map
        return result

    graph_builder = StateGraph(State)
    graph_builder.add_node("flight_chat", flight_chat)
    graph_builder.add_node("tools", tool_node)
    graph_builder.add_edge(START, "flight_chat")
    graph_builder.add_conditional_edges("flight_chat", tools_condition)
    graph_builder.add_edge("tools", "flight_chat")

    memory = MemorySaver()
    return graph_builder.compile(checkpointer=memory, name="flight_agent")