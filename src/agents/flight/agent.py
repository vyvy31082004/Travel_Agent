from typing import Annotated

from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, StateGraph
from langgraph.prebuilt import InjectedState, ToolNode, tools_condition
from dotenv import load_dotenv

from agents.flight.state import State
from agents.flight.tools import get_flight_tools
from memory.agent_helpers import domain_chat_with_memory
from memory.long_term import MemoryDomain
from memory.recall_nodes import make_domain_memory_recall_node
from memory.tool_wrapper import wrap_tools_with_result_store
from prompts.prompt import flight_prompts
from repositories.result_store import ResultStoreRepository
from services.long_term_memory import MemoryService
from services.reference_resolver import ClarificationNeeded, resolve_item_reference
from utils.api_client_flight import get_booking_link_from_api
from utils.tracing import with_trace_config

load_dotenv()

llm = ChatGoogleGenerativeAI(
    model="gemini-3.6-flash",
)


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
    The detailToken is resolved automatically from the session checkpointer / Result Store.

    cabin_class values: 'economy', 'business', 'first', 'premium_economy'.
    """
    token_map: dict[str, str] = state.get("flight_token_map") or {}
    detail_token = token_map.get(flight_id)

    if not detail_token:
        resolved = resolve_item_reference(
            state, domain="flight", item_id=flight_id
        )
        repo = state.get("_result_store")
        # Injected via config in chat path when available through runnable config is preferred;
        # fallback stays on token map / clarification.
        if isinstance(resolved, ClarificationNeeded):
            return {"error": resolved.reason}
        # detail_token may still be missing without repo access here.
        _ = repo  # reserved for future InjectedToolArg wiring

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


async def build_flight_graph(
    *,
    repo: ResultStoreRepository | None = None,
    memory_service: MemoryService | None = None,
):
    mcp_tools = await get_flight_tools()
    mcp_tools = [t for t in mcp_tools if t.name != "book_flight"]
    if repo is not None:
        mcp_tools = wrap_tools_with_result_store(mcp_tools, repo)

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
        # After search, hydrate flight_token_map from Result Store for displayed offers.
        updates = await domain_chat_with_memory(
            runnable=flight_runnable,
            state=state,
            config=config,
            domain_hint="flight",
            repo=repo,
        )

        if repo is not None:
            user_id = str(state.get("user_id") or "")
            thread_id = str(state.get("thread_id") or "")
            visible = state.get("visible_results") or {}
            latest = (state.get("latest_request_by_domain") or {}).get("flight")
            # Prefer newly extracted visible results from this turn.
            merged_visible = {
                **visible,
                **(updates.get("visible_results") or {}),
            }
            request_id = (updates.get("latest_request_by_domain") or {}).get(
                "flight"
            ) or latest
            if user_id and thread_id and request_id and request_id in merged_visible:
                ref = merged_visible[request_id]
                try:
                    items = await repo.load_items(
                        search_id=ref["search_id"],
                        item_ids=ref.get("displayed_item_ids") or [],
                        user_id=user_id,
                        thread_id=thread_id,
                    )
                    token_map = {
                        str(item["item_id"]): str(item["detail_token"])
                        for item in items
                        if item.get("item_id") and item.get("detail_token")
                    }
                    if token_map:
                        updates["flight_token_map"] = {
                            **(updates.get("flight_token_map") or {}),
                            **token_map,
                        }
                except Exception:
                    pass

        # Remind model that tokens stay internal (payloads already sanitized).
        response_messages = updates.get("messages") or []
        if response_messages and not getattr(response_messages[0], "tool_calls", None):
            pass
        return updates

    graph_builder = StateGraph(State)
    graph_builder.add_node(
        "memory_recall_flight",
        make_domain_memory_recall_node(
            memory_service,
            domain=MemoryDomain.FLIGHT,
            llm=llm,
            node_name="memory_recall_flight",
        ),
    )
    graph_builder.add_node("flight_chat", flight_chat)
    graph_builder.add_node("tools", tool_node)
    graph_builder.add_edge(START, "memory_recall_flight")
    graph_builder.add_edge("memory_recall_flight", "flight_chat")
    graph_builder.add_conditional_edges("flight_chat", tools_condition)
    graph_builder.add_edge("tools", "flight_chat")

    memory = MemorySaver()
    return graph_builder.compile(checkpointer=memory, name="flight_agent")
