import asyncio
import warnings
from copy import copy

from dotenv import load_dotenv
from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig, RunnableLambda
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from pydantic import BaseModel

from agents.excursion.agent import build_excursion_graph
from agents.flight.agent import build_flight_graph
from agents.hotel.agent import build_hotel_graph
from agents.primary.state import State
from prompts.prompt import primary_prompts

warnings.filterwarnings("ignore")
load_dotenv()


llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.2,
)


class ToHotelAssistant(BaseModel):
    """Chuyển công việc cho hotel agent để xử lý việc tìm, đặt hoặc huỷ phòng khách sạn."""


class ToExcursionAssistant(BaseModel):
    """Chuyển công việc cho excursion agent để xử lý việc tìm thông tin cho các chuyến dã ngoại."""


class ToFlightAssistant(BaseModel):
    """Chuyển công việc cho flight agent để xử lý việc tìm thông tin cho các chuyến bay."""


TOOL_TO_ASSISTANT = {
    ToHotelAssistant.__name__: ("hotel_assistant", "Hotel Booking Assistant"),
    ToExcursionAssistant.__name__: (
        "excursion_assistant",
        "Trip Recommendation Assistant",
    ),
    ToFlightAssistant.__name__: ("flight_assistant", "Flight Booking Assistant"),
}

ASSISTANT_NODES = ["hotel_assistant", "excursion_assistant", "flight_assistant"]

primary_runnable = primary_prompts | llm.bind_tools(
    [ToHotelAssistant, ToExcursionAssistant, ToFlightAssistant]
)


async def primary_chat(state: State, config: RunnableConfig) -> dict:
    result = await primary_runnable.ainvoke(state, config=config)
    return {"messages": [result]}


def _copy_last_ai_with_single_tool_call(state: State, tool_call: dict):
    last_message = state["messages"][-1]
    branch_message = copy(last_message)
    branch_message.tool_calls = [tool_call]
    return branch_message


def _branch_state(state: State, tool_call: dict, node_name: str) -> dict:
    return {
        **state,
        "messages": state["messages"][:-1]
        + [_copy_last_ai_with_single_tool_call(state, tool_call)],
        "tool_call_id": tool_call["id"],
        "active_assistant": node_name,
    }


def generic_assistant_entry(state: State, assistant_name: str, dialog_state: str) -> dict:
    tcid = state.get("tool_call_id")
    if not tcid:
        last_message = state["messages"][-1]
        tcid = (
            last_message.tool_calls[0]["id"]
            if getattr(last_message, "tool_calls", None)
            else None
        )

    next_state = dict(state)
    next_messages = list(state.get("messages", []))

    if tcid:
        next_messages.append(
            ToolMessage(
                content=(
                    f"The assistant is now the {assistant_name}. Reflect on the conversation above.\n"
                    f"ANSWERING RULES:\n"
                    f"- Answer ONLY within the scope of {assistant_name}.\n"
                    f"- Do NOT mention limitations or other domains.\n"
                    f"- If you use a tool, you MUST use the exact output of the tool in your final response (especially numbers and prices).\n"
                    f"- Return concise, structured results. Prefer a single bullet list or a short JSON payload.\n"
                ),
                tool_call_id=tcid,
            )
        )

    next_state["messages"] = next_messages
    next_state["dialog_state"] = dialog_state
    return next_state


def route_primary_assistant(state: State):
    tool_calls = getattr(state["messages"][-1], "tool_calls", None) or []
    sends = []

    for tool_call in tool_calls:
        assistant_info = TOOL_TO_ASSISTANT.get(tool_call["name"])
        if not assistant_info:
            continue

        node_name, _ = assistant_info
        sends.append(Send(node_name, _branch_state(state, tool_call, node_name)))

    return sends or END


def join_results(state: State) -> dict:
    return {
        "dialog_state": "pop",
        "tool_call_id": None,
        "active_assistant": None,
    }


async def build_primary_graph():
    flight_graph, hotel_graph, excursion_graph = await asyncio.gather(
        build_flight_graph(),
        build_hotel_graph(),
        build_excursion_graph(),
    )

    builder = StateGraph(State)

    builder.add_node("primary_assistant", primary_chat)
    builder.add_edge(START, "primary_assistant")
    builder.add_conditional_edges(
        "primary_assistant",
        route_primary_assistant,
        ASSISTANT_NODES + [END],
    )

    builder.add_node(
        "hotel_assistant",
        RunnableLambda(
            lambda s: generic_assistant_entry(
                s, "Hotel Booking Assistant", "hotel_assistant"
            )
        ).with_config({"run_name": "enter_hotel_assistant"})
        | hotel_graph.with_config({"run_name": "hotel_agent"}),
    )
    builder.add_node(
        "excursion_assistant",
        RunnableLambda(
            lambda s: generic_assistant_entry(
                s, "Trip Recommendation Assistant", "excursion_assistant"
            )
        ).with_config({"run_name": "enter_excursion_assistant"})
        | excursion_graph.with_config({"run_name": "excursion_agent"}),
    )
    builder.add_node(
        "flight_assistant",
        RunnableLambda(
            lambda s: generic_assistant_entry(
                s, "Flight Booking Assistant", "flight_assistant"
            )
        ).with_config({"run_name": "enter_flight_assistant"})
        | flight_graph.with_config({"run_name": "flight_agent"}),
    )

    builder.add_node("join_results", join_results)

    for node_name in ASSISTANT_NODES:
        builder.add_edge(node_name, "join_results")

    builder.add_edge("join_results", END)

    memory = InMemorySaver()
    return builder.compile(checkpointer=memory, name="primary_agent")
