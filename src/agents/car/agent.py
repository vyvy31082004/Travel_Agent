from langchain_core.runnables import RunnableConfig
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from dotenv import load_dotenv

from agents.car.state import State
from agents.car.tools import get_car_tools
from memory.agent_helpers import domain_chat_with_memory
from memory.long_term import MemoryDomain
from memory.recall_nodes import make_domain_memory_recall_node
from memory.tool_wrapper import wrap_tools_with_result_store
from prompts.prompt import car_prompts
from repositories.result_store import ResultStoreRepository
from services.long_term_memory import MemoryService
from utils.tracing import with_trace_config

load_dotenv()

llm = ChatGoogleGenerativeAI(
    model="gemini-3.6-flash",
)


async def build_car_graph(
    *,
    repo: ResultStoreRepository | None = None,
    memory_service: MemoryService | None = None,
):
    car_tools = await get_car_tools()
    if repo is not None:
        car_tools = wrap_tools_with_result_store(car_tools, repo)

    car_runnable = (car_prompts | llm.bind_tools(car_tools)).with_config(
        with_trace_config(
            run_name="car_llm",
            tags=["customer-support", "car", "llm"],
            metadata={"agent": "car"},
        )
    )
    tool_node = ToolNode(car_tools).with_config(
        with_trace_config(
            run_name="car_tools",
            tags=["customer-support", "car", "tools", "mcp"],
            metadata={"agent": "car", "tool_transport": "mcp_sse"},
        )
    )

    async def car_chat(state: dict, config: RunnableConfig):
        return await domain_chat_with_memory(
            runnable=car_runnable,
            state=state,
            config=config,
            domain_hint="car",
            repo=repo,
        )

    graph_builder = StateGraph(State)
    graph_builder.add_node(
        "memory_recall_car",
        make_domain_memory_recall_node(
            memory_service,
            domain=MemoryDomain.CAR,
            llm=llm,
            node_name="memory_recall_car",
        ),
    )
    graph_builder.add_node("car_chat", car_chat)
    graph_builder.add_node("tools", tool_node)
    graph_builder.add_edge(START, "memory_recall_car")
    graph_builder.add_edge("memory_recall_car", "car_chat")
    graph_builder.add_conditional_edges("car_chat", tools_condition)
    graph_builder.add_edge("tools", "car_chat")
    return graph_builder.compile(name="car_agent")
