from dotenv import load_dotenv
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from agents.travel_planner.state import State
from agents.travel_planner.tools import get_travel_planner_tools
from prompts.prompt import travel_planner_prompts
from utils.tracing import with_trace_config

load_dotenv()

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.2,
)

REQUIRED_PLAN_TOOL_GROUPS = (
    ("get_weather_tool",),
    ("search_attractions_tool",),
    ("search_hotels_tool",),
    ("search_cars_tool",),
    ("search_round_trip_flights_tool", "search_one_way_flights_tool"),
)

TOOL_ERROR_MARKERS = (
    '"error"',
    "giới hạn request",
    "rate limit",
    "too many requests",
)


def _planner_recovery_message(messages):
    called_tools = {
        tool_call["name"]
        for message in messages
        if isinstance(message, AIMessage)
        for tool_call in message.tool_calls
    }
    latest_message = messages[-1] if messages else None
    latest_tool_failed = (
        isinstance(latest_message, ToolMessage)
        and any(
            marker in str(latest_message.content).lower()
            for marker in TOOL_ERROR_MARKERS
        )
    )
    if not latest_tool_failed:
        return None

    remaining_groups = [
        "/".join(group)
        for group in REQUIRED_PLAN_TOOL_GROUPS
        if not any(tool_name in called_tools for tool_name in group)
    ]
    if not remaining_groups:
        return SystemMessage(
            content=(
                "The latest tool failed after its internal retry policy. "
                "Do not call it again. Synthesize the final plan now and include "
                "the exact error in that tool's section."
            )
        )

    return SystemMessage(
        content=(
            "The latest tool failed after its internal retry policy and counts as "
            "attempted. Do not call that tool again. Continue the required workflow. "
            f"Tools still not attempted: {', '.join(remaining_groups)}. "
            "Call the next appropriate missing tool now; do not merely say that you "
            "will continue or retry."
        )
    )


async def build_travel_planner_graph():
    travel_planner_tools = await get_travel_planner_tools()
    travel_planner_runnable = (
        travel_planner_prompts | llm.bind_tools(travel_planner_tools)
    ).with_config(
        with_trace_config(
            run_name="travel_planner_llm",
            tags=["customer-support", "travel-planner", "llm"],
            metadata={"agent": "travel_planner"},
        )
    )
    tool_node = ToolNode(travel_planner_tools).with_config(
        with_trace_config(
            run_name="travel_planner_tools",
            tags=["customer-support", "travel-planner", "tools", "mcp"],
            metadata={"agent": "travel_planner", "tool_transport": "mcp_sse"},
        )
    )

    async def travel_planner_chat(state: State, config: RunnableConfig):
        invocation_state = state
        recovery_message = _planner_recovery_message(state["messages"])
        if recovery_message:
            invocation_state = {
                **state,
                "messages": [*state["messages"], recovery_message],
            }
        response = await travel_planner_runnable.ainvoke(
            invocation_state,
            config=with_trace_config(
                config,
                run_name="travel_planner_chat",
                tags=["customer-support", "travel-planner"],
                metadata={"agent": "travel_planner"},
            ),
        )
        if isinstance(response, list):
            return {"messages": response}
        return {"messages": [response]}

    graph_builder = StateGraph(State)
    graph_builder.add_node("travel_planner_chat", travel_planner_chat)
    graph_builder.add_node("tools", tool_node)
    graph_builder.add_edge(START, "travel_planner_chat")
    graph_builder.add_conditional_edges("travel_planner_chat", tools_condition)
    graph_builder.add_edge("tools", "travel_planner_chat")
    return graph_builder.compile(name="travel_planner_agent")
