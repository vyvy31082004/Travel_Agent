import asyncio
import logging
import warnings
from copy import copy

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from pydantic import BaseModel

from agents.excursion.agent import build_excursion_graph
from agents.flight.agent import build_flight_graph
from agents.hotel.agent import build_hotel_graph
from agents.car.agent import build_car_graph
from agents.travel_planner.agent import build_travel_planner_graph
from agents.primary.state import State
from memory.agent_helpers import merge_structured_state
from prompts.prompt import primary_prompts
from repositories.result_store import ResultStoreRepository
from services.long_term_memory import MemoryService, config_user_thread
from services.summarize import should_summarize, summarize_conversation
from utils.tracing import with_trace_config

warnings.filterwarnings("ignore")
load_dotenv()

logger = logging.getLogger(__name__)


llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.2,
)


class ToHotelAssistant(BaseModel):
    """Chuyển công việc cho hotel agent để xử lý việc tìm, đặt hoặc huỷ phòng khách sạn."""
    request: str

class ToExcursionAssistant(BaseModel):
    """Chuyển công việc cho excursion agent để xử lý việc tìm thông tin cho các chuyến dã ngoại."""
    request: str

class ToFlightAssistant(BaseModel):
    """Chuyển công việc cho flight agent để xử lý việc tìm thông tin cho các chuyến bay."""
    request: str

class ToCarAssistant(BaseModel):
    """Chuyển công việc cho car agent để xử lý việc tìm thông tin cho các chỗ cho thuê xe."""
    request: str

class ToTravelPlannerAssistant(BaseModel):
    """Chuyển công việc cho travel planner để lên kế hoạch du lịch tổng hợp
    (thời tiết, hoạt động phù hợp, khách sạn, chuyến bay, xe)."""
    request: str

TOOL_TO_ASSISTANT = {
    ToHotelAssistant.__name__: ("hotel_assistant", "Hotel Booking Assistant"),
    ToExcursionAssistant.__name__: (
        "excursion_assistant",
        "Trip Recommendation Assistant",
    ),
    ToFlightAssistant.__name__: ("flight_assistant", "Flight Booking Assistant"),
    ToCarAssistant.__name__: ("car_assistant", "Car Booking Assistant"),
    ToTravelPlannerAssistant.__name__: (
        "travel_planner_assistant",
        "Travel Planner Assistant",
    ),
}

ASSISTANT_NODES = [
    "hotel_assistant",
    "excursion_assistant",
    "flight_assistant",
    "car_assistant",
    "travel_planner_assistant",
]

primary_runnable = (
    primary_prompts | llm.bind_tools(
        [
            ToHotelAssistant,
            ToExcursionAssistant,
            ToFlightAssistant,
            ToCarAssistant,
            ToTravelPlannerAssistant,
        ]
    )
).with_config(
    with_trace_config(
        run_name="primary_llm",
        tags=["customer-support", "primary", "llm"],
        metadata={"agent": "primary"},
    )
)


async def primary_chat(state: State, config: RunnableConfig) -> dict:
    invoke_state = dict(state)
    messages = list(state.get("messages") or [])
    context_messages: list[SystemMessage] = []
    if state.get("summary"):
        context_messages.append(
            SystemMessage(
                content=f"Bản tóm tắt hội thoại đến hiện tại:\n{state['summary']}"
            )
        )
    if state.get("memory_context"):
        context_messages.append(
            SystemMessage(
                content=(
                    "Long-term user memory recalled across conversations. "
                    "Treat it as durable preference/profile context, not as "
                    "temporary tool results.\n"
                    f"{state['memory_context']}"
                )
            )
        )
    if context_messages:
        invoke_state["messages"] = [*context_messages, *messages]

    result = await primary_runnable.ainvoke(
        invoke_state,
        config=with_trace_config(
            config,
            run_name="primary_assistant",
            tags=["customer-support", "primary"],
            metadata={"agent": "primary"},
        ),
    )
    return {"messages": [result]}


def _copy_last_ai_with_single_tool_call(state: State, tool_call: dict):
    last_message = state["messages"][-1]
    branch_message = copy(last_message)
    branch_message.tool_calls = [tool_call]
    return branch_message


def _branch_state(state: State, tool_call: dict, node_name: str) -> dict:
    return {
        **state,
        "messages": [_copy_last_ai_with_single_tool_call(state, tool_call)],
        "tool_call_id": tool_call["id"],
        "active_assistant": node_name,
    }


def _delegated_request_from_state(state: State) -> tuple[str | None, str]:
    tcid = state.get("tool_call_id")
    last_message = state["messages"][-1]
    tool_calls = getattr(last_message, "tool_calls", None) or []
    tool_call = tool_calls[0] if tool_calls else {}
    if not tcid and tool_call:
        tcid = tool_call["id"]
    return tcid, tool_call.get("args", {}).get("request", "")


def _assistant_result_text(messages: list, fallback: str) -> str:
    for message in reversed(messages):
        content = getattr(message, "content", None)
        if content:
            return content if isinstance(content, str) else str(content)
    return fallback


async def run_delegated_assistant(
    state: State,
    assistant_graph,
    assistant_name: str,
    dialog_state: str,
    config: RunnableConfig,
) -> dict:
    tcid, delegated_request = _delegated_request_from_state(state)
    assistant_domain = dialog_state.replace("_assistant", "")
    if dialog_state == "travel_planner_assistant":
        answering_rules = (
            f"ANSWERING RULES:\n"
            f"- You are the {assistant_name}. Build a practical multi-domain trip plan.\n"
            f"- Use weather, attractions, hotel, flight, and/or car tools as needed for this request.\n"
            f"- Follow weather-first planning when the user asks for a weather-based plan.\n"
            f"- If you use a tool, you MUST use the exact output of the tool in your final response "
            f"(especially numbers and prices).\n"
            f"- Search tools return compact refs; temporary Result Store payloads are injected for answering.\n"
            f"- Synthesize one clear itinerary covering the requested parts "
            f"(weather summary, matching activities, hotels, flights).\n"
            f"- Answer ONLY this delegated request, not unrelated conversation history.\n"
        )
    else:
        answering_rules = (
            f"ANSWERING RULES:\n"
            f"- Answer ONLY within the scope of {assistant_name}.\n"
            f"- Do NOT mention limitations or other domains.\n"
            f"- Search tools return compact refs (search_id, displayed_item_ids, labels). "
            f"Full payloads are injected temporarily from Result Store — use them for the answer.\n"
            f"- For ordinal requests ('thứ 2', 'cái thứ 3'), use the injected RESOLVED ITEM / "
            f"visible list. Map position by code-provided item_id. Do NOT invent IDs and "
            f"do NOT output CompleteOrEscalate when resolved context is present.\n"
            f"- If you use a tool, you MUST use the exact output of the tool / temporary payload "
            f"in your final response (especially numbers and prices).\n"
            f"- Return concise, structured results. Prefer a single bullet list.\n"
            f"- Answer ONLY this delegated request, not the original user message.\n"
            f"- Ignore all unrelated parts of the original conversation.\n"
        )
    configurable = dict((config or {}).get("configurable") or {})
    assistant_input = {
        **state,
        "messages": [
            HumanMessage(
                content=(
                    f"Delegated user request:\n{delegated_request}\n\n"
                    f"{answering_rules}"
                )
            )
        ],
        "dialog_state": dialog_state,
        "active_assistant": dialog_state,
        "user_id": state.get("user_id") or configurable.get("user_id"),
        "thread_id": state.get("thread_id") or configurable.get("thread_id"),
    }
    delegated_config = with_trace_config(
        config,
        run_name=f"delegated_{dialog_state}",
        tags=["customer-support", "primary", "delegation", assistant_domain],
        metadata={
            "agent": "primary",
            "assistant_name": assistant_name,
            "dialog_state": dialog_state,
            "tool_call_id": tcid,
        },
    )
    result = await assistant_graph.ainvoke(assistant_input, config=delegated_config)
    result_messages = result.get("messages", [])

    if not tcid:
        output = {"messages": []}
    else:
        output = {
            "messages": [
                ToolMessage(
                    content=_assistant_result_text(
                        result_messages,
                        f"{assistant_name} completed the delegated request.",
                    ),
                    tool_call_id=tcid,
                )
            ]
        }
    output.update(merge_structured_state(result))
    return output


def route_primary_assistant(state: State):
    tool_calls = getattr(state["messages"][-1], "tool_calls", None) or []
    sends = []

    for tool_call in tool_calls:
        assistant_info = TOOL_TO_ASSISTANT.get(tool_call["name"])
        if not assistant_info:
            continue

        node_name, _ = assistant_info
        sends.append(Send(node_name, _branch_state(state, tool_call, node_name)))

    if sends:
        return sends
    return should_summarize(state)


def join_results(state: State) -> dict:
    return {
        "dialog_state": "pop",
        "tool_call_id": None,
        "active_assistant": None,
    }


async def summarize_node(state: State, config: RunnableConfig) -> dict:
    return await summarize_conversation(state, llm)




def _last_user_text(state: State) -> str:
    for message in reversed(state.get("messages") or []):
        message_type = getattr(message, "type", None)
        if message_type in {"human", "user"}:
            content = getattr(message, "content", "")
            return content if isinstance(content, str) else str(content)
        if isinstance(message, tuple) and len(message) >= 2 and message[0] in {"user", "human"}:
            return str(message[1])
    return ""


def _last_ai_message_id(state: State) -> str | None:
    for message in reversed(state.get("messages") or []):
        if getattr(message, "type", None) in {"ai", "assistant"}:
            return getattr(message, "id", None)
    return None


async def build_primary_graph(
    *,
    checkpointer: BaseCheckpointSaver,
    repo: ResultStoreRepository | None = None,
    memory_service: MemoryService | None = None,
):
    flight_graph, hotel_graph, excursion_graph, car_graph, travel_planner_graph = (
        await asyncio.gather(
            build_flight_graph(repo=repo),
            build_hotel_graph(repo=repo),
            build_excursion_graph(repo=repo),
            build_car_graph(repo=repo),
            build_travel_planner_graph(repo=repo),
        )
    )

    builder = StateGraph(State)

    async def memory_recall_node(state: State, config: RunnableConfig) -> dict:
        if memory_service is None:
            return {"memory_context": "", "recalled_memory_ids": []}
        user_id, _ = config_user_thread(config)
        recall = await memory_service.recall(
            user_id=state.get("user_id") or user_id,
            query=_last_user_text(state),
        )
        return {
            "memory_context": recall.memory_context,
            "recalled_memory_ids": recall.recalled_memory_ids,
        }

    async def memory_finalize_node(state: State, config: RunnableConfig) -> dict:
        if memory_service is None:
            return {}
        user_id, thread_id = config_user_thread(config)
        try:
            job = await memory_service.enqueue_final_turn(
                user_id=state.get("user_id") or user_id,
                thread_id=state.get("thread_id") or thread_id,
                final_message_id=_last_ai_message_id(state),
                checkpoint_id=None,
                messages=state.get("messages") or [],
                metadata={"recalled_memory_ids": state.get("recalled_memory_ids") or []},
            )
        except Exception as exc:
            logger.warning("memory finalize enqueue failed: %s", exc)
            return {"memory_job_id": None}
        return {"memory_job_id": job.job_id if job else None}

    builder.add_node("memory_recall", memory_recall_node)
    builder.add_node("primary_assistant", primary_chat)
    builder.add_edge(START, "memory_recall")
    builder.add_edge("memory_recall", "primary_assistant")
    builder.add_conditional_edges(
        "primary_assistant",
        route_primary_assistant,
        {
            **{node: node for node in ASSISTANT_NODES},
            "summarize_conversation": "summarize_conversation",
            "__end__": "memory_finalize",
        },
    )

    async def hotel_assistant_node(state: State, config: RunnableConfig) -> dict:
        return await run_delegated_assistant(
            state,
            hotel_graph,
            "Hotel Booking Assistant",
            "hotel_assistant",
            config,
        )

    async def excursion_assistant_node(state: State, config: RunnableConfig) -> dict:
        return await run_delegated_assistant(
            state,
            excursion_graph,
            "Trip Recommendation Assistant",
            "excursion_assistant",
            config,
        )

    async def flight_assistant_node(state: State, config: RunnableConfig) -> dict:
        return await run_delegated_assistant(
            state,
            flight_graph,
            "Flight Booking Assistant",
            "flight_assistant",
            config,
        )

    async def car_assistant_node(state: State, config: RunnableConfig) -> dict:
        return await run_delegated_assistant(
            state,
            car_graph,
            "Car Booking Assistant",
            "car_assistant",
            config,
        )

    async def travel_planner_assistant_node(
        state: State, config: RunnableConfig
    ) -> dict:
        return await run_delegated_assistant(
            state,
            travel_planner_graph,
            "Travel Planner Assistant",
            "travel_planner_assistant",
            config,
        )

    builder.add_node("hotel_assistant", hotel_assistant_node)
    builder.add_node("excursion_assistant", excursion_assistant_node)
    builder.add_node("flight_assistant", flight_assistant_node)
    builder.add_node("car_assistant", car_assistant_node)
    builder.add_node("travel_planner_assistant", travel_planner_assistant_node)

    builder.add_node("join_results", join_results)
    builder.add_node("summarize_conversation", summarize_node)
    builder.add_node("memory_finalize", memory_finalize_node)

    for node_name in ASSISTANT_NODES:
        builder.add_edge(node_name, "join_results")

    builder.add_edge("join_results", "primary_assistant")
    builder.add_edge("summarize_conversation", "memory_finalize")
    builder.add_edge("memory_finalize", END)

    return builder.compile(checkpointer=checkpointer, name="primary_agent")
