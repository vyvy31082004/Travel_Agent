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
from pydantic import BaseModel, Field

from agents.car.agent import build_car_graph
from agents.excursion.agent import build_excursion_graph
from agents.flight.agent import build_flight_graph
from agents.hotel.agent import build_hotel_graph
from agents.primary.domain_result import build_domain_branch_result
from agents.primary.state import State
from agents.primary.trip_delegation import normalize_branch_args, resolve_delegated_request
from memory.agent_helpers import merge_structured_state
from memory.long_term import MemoryDomain
from memory.recall_nodes import make_domain_memory_recall_node, make_global_recall_node
from agents.primary.domain_scope import build_domain_scoped_state
from prompts.prompt import primary_prompts
from repositories.result_store import ResultStoreRepository
from services.long_term_memory import MemoryService, config_user_thread
from services.summarize import (
    e2e_summarize_all_enabled,
    should_summarize,
    summarize_conversation,
)
from e2e_eval.trace_collector import trace_collector_from_config
from utils.tracing import with_trace_config

warnings.filterwarnings("ignore")
load_dotenv()

logger = logging.getLogger(__name__)


llm = ChatGoogleGenerativeAI(
    model="gemini-3.6-flash",
)


class ToHotelAssistant(BaseModel):
    """Chuyển công việc cho hotel agent để xử lý việc tìm, đặt hoặc huỷ phòng khách sạn."""
    request: str
    turn_constraints: list[str] = Field(default_factory=list)


class ToExcursionAssistant(BaseModel):
    """Chuyển công việc cho excursion agent để xử lý việc tìm thông tin cho các chuyến dã ngoại."""
    request: str
    turn_constraints: list[str] = Field(default_factory=list)


class ToFlightAssistant(BaseModel):
    """Chuyển công việc cho flight agent để xử lý việc tìm thông tin cho các chuyến bay."""
    request: str
    turn_constraints: list[str] = Field(default_factory=list)


class ToCarAssistant(BaseModel):
    """Chuyển công việc cho car agent để xử lý việc tìm thông tin cho các chỗ cho thuê xe."""
    request: str
    turn_constraints: list[str] = Field(default_factory=list)


TOOL_TO_BRANCH = {
    ToHotelAssistant.__name__: (
        "hotel_assistant",
        "Hotel Booking Assistant",
        MemoryDomain.HOTEL.value,
    ),
    ToExcursionAssistant.__name__: (
        "excursion_assistant",
        "Trip Recommendation Assistant",
        MemoryDomain.EXCURSION.value,
    ),
    ToFlightAssistant.__name__: (
        "flight_assistant",
        "Flight Booking Assistant",
        MemoryDomain.FLIGHT.value,
    ),
    ToCarAssistant.__name__: (
        "car_assistant",
        "Car Booking Assistant",
        MemoryDomain.CAR.value,
    ),
}

ASSISTANT_NODES = [
    "hotel_assistant",
    "excursion_assistant",
    "flight_assistant",
    "car_assistant",
]

primary_runnable = (
    primary_prompts
    | llm.bind_tools(
        [
            ToHotelAssistant,
            ToExcursionAssistant,
            ToFlightAssistant,
            ToCarAssistant,
        ]
    )
).with_config(
    with_trace_config(
        run_name="primary_llm",
        tags=["customer-support", "primary", "llm"],
        metadata={"agent": "primary"},
    )
)


def _format_domain_branch_results(results: list[dict]) -> str:
    if not results:
        return ""
    lines = [
        "Structured domain branch results (canonical for synthesis):",
        "MANDATORY: For each branch option below, your final answer MUST include "
        "EVERY item_id in displayed_item_ids — same count, preserve list order. "
        "Do NOT omit, merge away, or skip any displayed item. "
        "Do NOT add items outside displayed_item_ids.",
    ]
    for item in results:
        domain = item.get("domain", "unknown")
        lines.append(f"\n[{domain}]")
        if item.get("applied_constraints"):
            lines.append(
                "Applied constraints: "
                + "; ".join(str(c) for c in item["applied_constraints"])
            )
        if item.get("warnings"):
            lines.append("Warnings: " + "; ".join(str(w) for w in item["warnings"]))
        for idx, option in enumerate(item.get("options") or [], start=1):
            displayed = list(option.get("displayed_item_ids") or [])
            if not displayed:
                continue
            lines.append(
                f"Option {idx} displayed_item_ids ({len(displayed)} items, include ALL): "
                + ", ".join(str(item_id) for item_id in displayed)
            )
            if option.get("search_id"):
                lines.append(f"  search_id: {option['search_id']}")
        if item.get("summary"):
            lines.append(f"Summary: {item['summary']}")
    return "\n".join(lines)


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
                    "Long-term global memory (profile, interaction rules, general "
                    "preferences). Treat as durable context, not temporary tool results.\n"
                    f"{state['memory_context']}"
                )
            )
        )
    branch_results: list[dict] = []
    if messages:
        last = messages[-1]
        if getattr(last, "type", None) not in {"human", "user"}:
            branch_results = list(state.get("domain_branch_results") or [])
    if branch_results:
        context_messages.append(
            SystemMessage(
                content=(
                    "You received results from specialized domain assistants. "
                    "Synthesize the final answer or trip itinerary from these results. "
                    "Check compatibility (dates, budget, constraints). "
                    "Include EVERY item in each option's displayed_item_ids — do not drop any. "
                    "Do NOT call delegation tools again.\n"
                    f"{_format_domain_branch_results(branch_results)}"
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


def _latest_human_message(state: State) -> str:
    for message in reversed(state.get("messages") or []):
        if isinstance(message, HumanMessage):
            content = message.content
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, str):
                        parts.append(block)
                    elif isinstance(block, dict) and block.get("text"):
                        parts.append(str(block["text"]))
                return "\n".join(parts)
            return str(content or "")
        if getattr(message, "type", None) in {"human", "user"}:
            content = getattr(message, "content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, str):
                        parts.append(block)
                    elif isinstance(block, dict) and block.get("text"):
                        parts.append(str(block["text"]))
                return "\n".join(parts)
            return str(content or "")
        if isinstance(message, tuple) and len(message) >= 2 and message[0] in {"user", "human"}:
            return str(message[1])
    return ""


def _branch_state(state: State, tool_call: dict) -> dict:
    user_message = (
        state.get("trip_plan_user_message")
        or _latest_human_message(state)
    )
    raw_args = tool_call.get("args", {}) or {}
    assistant_node = TOOL_TO_BRANCH[tool_call["name"]][0]
    args = normalize_branch_args(
        tool_call["name"],
        raw_args,
        user_message,
        assistant_node=assistant_node,
    )
    branch_tool_call = {**tool_call, "args": args}
    return {
        **state,
        "messages": [_copy_last_ai_with_single_tool_call(state, branch_tool_call)],
        "tool_call_id": tool_call["id"],
        "active_assistant": assistant_node,
        "delegated_request": args.get("request", ""),
        "turn_constraints": list(args.get("turn_constraints") or []),
        "trip_plan_user_message": user_message,
        "user_query": user_message,
        "domain_memory_context": "",
        "domain_soft_memory_context": "",
        "memory_applicability": [],
        "domain_action": None,
    }


def _delegated_request_from_state(state: State) -> tuple[str | None, str]:
    tcid = state.get("tool_call_id")
    delegated = (state.get("delegated_request") or "").strip()
    if not delegated:
        last_message = state["messages"][-1]
        tool_calls = getattr(last_message, "tool_calls", None) or []
        tool_call = tool_calls[0] if tool_calls else {}
        if not tcid and tool_call:
            tcid = tool_call["id"]
        delegated = tool_call.get("args", {}).get("request", "")
    return tcid, delegated


def _assistant_result_text(messages: list, fallback: str) -> str:
    for message in reversed(messages):
        content = getattr(message, "content", None)
        if content:
            return content if isinstance(content, str) else str(content)
    return fallback


def _format_turn_constraints(constraints: list[str]) -> str:
    if not constraints:
        return ""
    lines = "\n".join(f"- {item}" for item in constraints)
    return f"\n\nTurn constraints for this domain (apply now):\n{lines}\n"


async def _invoke_assistant_graph(
    assistant_graph,
    assistant_input: dict,
    config: RunnableConfig,
    *,
    collector,
    dialog_state: str,
    domain: str,
) -> dict:
    if collector is None:
        return await assistant_graph.ainvoke(assistant_input, config=config)

    result: dict | None = None
    try:
        async for event in assistant_graph.astream(
            assistant_input,
            config=config,
            stream_mode=["updates", "values"],
        ):
            if not isinstance(event, tuple) or len(event) != 2:
                continue
            mode, payload = event
            if mode == "values":
                result = payload
            elif mode == "updates":
                for node_name, update in payload.items():
                    collector.record_subgraph_node(
                        node_name,
                        graph=dialog_state,
                        domain=domain,
                        update=update,
                    )
    except (TypeError, ValueError):
        result = await assistant_graph.ainvoke(assistant_input, config=config)

    if result is None:
        result = await assistant_graph.ainvoke(assistant_input, config=config)
    return result


async def run_delegated_assistant(
    state: State,
    assistant_graph,
    assistant_name: str,
    dialog_state: str,
    domain: str,
    config: RunnableConfig,
) -> dict:
    tcid, delegated_request = _delegated_request_from_state(state)
    turn_constraints = list(state.get("turn_constraints") or [])
    user_message = (
        state.get("trip_plan_user_message")
        or _latest_human_message(state)
    )
    delegated_request, turn_constraints = resolve_delegated_request(
        domain,
        delegated_request,
        user_message,
        turn_constraints,
    )
    trip_plan_rule = ""
    if user_message and domain in {"hotel", "car", "excursion"}:
        trip_plan_rule = (
            "- TRIP PLAN SUB-TASK (mandatory): This is one slice of a multi-domain trip plan. "
            f"You MUST call your {domain} search tool now. "
            "Do NOT CompleteOrEscalate because flights, hotels, tours, or cars are handled by other assistants.\n"
        )
    answering_rules = (
        f"ANSWERING RULES:\n"
        f"- Answer ONLY within the scope of {assistant_name}.\n"
        f"- Do NOT mention limitations or other domains.\n"
        f"{trip_plan_rule}"
        f"- Search tools return compact refs (search_id, displayed_item_ids, labels). "
        f"Full payloads are injected temporarily from Result Store — use them for the answer.\n"
        f"- For ordinal requests ('thứ 2', 'cái thứ 3'), use the injected RESOLVED ITEM / "
        f"visible list. Map position by code-provided item_id. Do NOT invent IDs and "
        f"do NOT output CompleteOrEscalate when resolved context is present.\n"
        f"- If you use a tool, you MUST use the exact output of the tool / temporary payload "
        f"in your final response (especially numbers and prices).\n"
        f"- If long-term domain memory preferences are provided: AFTER the tool returns results, "
        f"FILTER what you print — only list items that match those preferences. "
        f"Omit non-matching items; do not invent new ones.\n"
        f"- Return concise, structured results. Prefer a single bullet list.\n"
        f"- Answer ONLY this delegated request, not the original user message.\n"
        f"- Ignore all unrelated parts of the original conversation.\n"
    )
    global_memory = (state.get("memory_context") or "").strip()
    configurable = dict((config or {}).get("configurable") or {})
    scoped_state = build_domain_scoped_state(state, domain)
    scoped_state.update(
        {
            "messages": [
                HumanMessage(
                    content=(
                        f"Delegated user request:\n{delegated_request}\n"
                        f"{_format_turn_constraints(turn_constraints)}"
                        f"{answering_rules}"
                    )
                )
            ],
            "dialog_state": dialog_state,
            "active_assistant": dialog_state,
            "user_id": state.get("user_id") or configurable.get("user_id"),
            "thread_id": state.get("thread_id") or configurable.get("thread_id"),
            "user_query": user_message,
            "delegated_request": delegated_request,
            "turn_constraints": turn_constraints,
        }
    )
    assistant_input = scoped_state
    delegated_config = with_trace_config(
        config,
        run_name=f"delegated_{dialog_state}",
        tags=["customer-support", "primary", "delegation", domain],
        metadata={
            "agent": "primary",
            "assistant_name": assistant_name,
            "dialog_state": dialog_state,
            "tool_call_id": tcid,
        },
    )
    collector = trace_collector_from_config(delegated_config)
    if collector:
        collector.record_assistant_boundary(dialog_state, domain)

    result = await _invoke_assistant_graph(
        assistant_graph,
        assistant_input,
        delegated_config,
        collector=collector,
        dialog_state=dialog_state,
        domain=domain,
    )
    result_messages = result.get("messages", [])
    summary = _assistant_result_text(
        result_messages,
        f"{assistant_name} completed the delegated request.",
    )
    branch_result = build_domain_branch_result(
        domain=domain,
        summary=summary,
        turn_constraints=turn_constraints,
        domain_memory_context=result.get("domain_memory_context")
        or state.get("domain_memory_context"),
        domain_soft_memory_context=result.get("domain_soft_memory_context")
        or state.get("domain_soft_memory_context"),
        domain_action=result.get("domain_action") or state.get("domain_action"),
        memory_applicability=result.get("memory_applicability")
        or state.get("memory_applicability"),
        visible_results=result.get("visible_results") or state.get("visible_results"),
    )

    output: dict = {
        "domain_branch_results": [branch_result.to_dict()],
        "recalled_memory_ids": list(result.get("recalled_memory_ids") or []),
    }
    if tcid:
        output["messages"] = [
            ToolMessage(content=branch_result.to_json(), tool_call_id=tcid)
        ]
    output.update(merge_structured_state(result))
    return output


def route_primary_assistant(state: State, config: RunnableConfig | None = None):
    tool_calls = getattr(state["messages"][-1], "tool_calls", None) or []
    sends = []

    for tool_call in tool_calls:
        branch_info = TOOL_TO_BRANCH.get(tool_call["name"])
        if not branch_info:
            continue
        assistant_node, _, _ = branch_info
        sends.append(Send(assistant_node, _branch_state(state, tool_call)))

    if sends:
        return sends
    return should_summarize(state, config=config)


def join_results(state: State) -> dict:
    return {
        "dialog_state": "pop",
        "tool_call_id": None,
        "active_assistant": None,
    }


async def summarize_node(state: State, config: RunnableConfig) -> dict:
    return await summarize_conversation(
        state,
        llm,
        summarize_all=e2e_summarize_all_enabled(config),
    )


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
    flight_graph, hotel_graph, excursion_graph, car_graph = await asyncio.gather(
        build_flight_graph(repo=repo, memory_service=memory_service),
        build_hotel_graph(repo=repo, memory_service=memory_service),
        build_excursion_graph(repo=repo, memory_service=memory_service),
        build_car_graph(repo=repo, memory_service=memory_service),
    )

    builder = StateGraph(State)

    builder.add_node(
        "memory_recall_global", make_global_recall_node(memory_service)
    )
    builder.add_node("primary_assistant", primary_chat)
    builder.add_edge(START, "memory_recall_global")
    builder.add_edge("memory_recall_global", "primary_assistant")

    recall_routes = {
        **{node: node for node in ASSISTANT_NODES},
        "summarize_conversation": "summarize_conversation",
        "__end__": "memory_finalize",
    }
    builder.add_conditional_edges(
        "primary_assistant",
        route_primary_assistant,
        recall_routes,
    )

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

    async def hotel_assistant_node(state: State, config: RunnableConfig) -> dict:
        return await run_delegated_assistant(
            state,
            hotel_graph,
            "Hotel Booking Assistant",
            "hotel_assistant",
            MemoryDomain.HOTEL.value,
            config,
        )

    async def excursion_assistant_node(state: State, config: RunnableConfig) -> dict:
        return await run_delegated_assistant(
            state,
            excursion_graph,
            "Trip Recommendation Assistant",
            "excursion_assistant",
            MemoryDomain.EXCURSION.value,
            config,
        )

    async def flight_assistant_node(state: State, config: RunnableConfig) -> dict:
        return await run_delegated_assistant(
            state,
            flight_graph,
            "Flight Booking Assistant",
            "flight_assistant",
            MemoryDomain.FLIGHT.value,
            config,
        )

    async def car_assistant_node(state: State, config: RunnableConfig) -> dict:
        return await run_delegated_assistant(
            state,
            car_graph,
            "Car Booking Assistant",
            "car_assistant",
            MemoryDomain.CAR.value,
            config,
        )

    builder.add_node("hotel_assistant", hotel_assistant_node)
    builder.add_node("excursion_assistant", excursion_assistant_node)
    builder.add_node("flight_assistant", flight_assistant_node)
    builder.add_node("car_assistant", car_assistant_node)

    builder.add_node("join_results", join_results)
    builder.add_node("summarize_conversation", summarize_node)
    builder.add_node("memory_finalize", memory_finalize_node)

    for node_name in ASSISTANT_NODES:
        builder.add_edge(node_name, "join_results")

    builder.add_edge("join_results", "primary_assistant")
    builder.add_edge("summarize_conversation", "memory_finalize")
    builder.add_edge("memory_finalize", END)

    return builder.compile(checkpointer=checkpointer, name="primary_agent")
