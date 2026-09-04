from langchain_core.runnables import RunnableConfig
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from dotenv import load_dotenv

from agents.hotel.state import State
from agents.hotel.tools import get_hotel_tools
from memory.agent_helpers import domain_chat_with_memory
from memory.long_term import MemoryDomain
from memory.recall_nodes import make_domain_memory_recall_node
from memory.tool_wrapper import wrap_tools_with_result_store
from prompts.prompt import hotel_prompts
from repositories.result_store import ResultStoreRepository
from services.long_term_memory import MemoryService
from utils.tracing import with_trace_config

load_dotenv()

llm = ChatGoogleGenerativeAI(
    model="gemini-3.6-flash",
)


async def build_hotel_graph(
    *,
    repo: ResultStoreRepository | None = None,
    memory_service: MemoryService | None = None,
):
    hotel_tools = await get_hotel_tools()
    if repo is not None:
        hotel_tools = wrap_tools_with_result_store(hotel_tools, repo)

    hotel_runnable = (hotel_prompts | llm.bind_tools(hotel_tools)).with_config(
        with_trace_config(
            run_name="hotel_llm",
            tags=["customer-support", "hotel", "llm"],
            metadata={"agent": "hotel"},
        )
    )
    tool_node = ToolNode(hotel_tools).with_config(
        with_trace_config(
            run_name="hotel_tools",
            tags=["customer-support", "hotel", "tools", "mcp"],
            metadata={"agent": "hotel", "tool_transport": "mcp_sse"},
        )
    )

    async def hotel_chat(state: dict, config: RunnableConfig):
        return await domain_chat_with_memory(
            runnable=hotel_runnable,
            state=state,
            config=config,
            domain_hint="hotel",
            repo=repo,
        )

    graph_builder = StateGraph(State)
    graph_builder.add_node(
        "memory_recall_hotel",
        make_domain_memory_recall_node(
            memory_service,
            domain=MemoryDomain.HOTEL,
            llm=llm,
            node_name="memory_recall_hotel",
        ),
    )
    graph_builder.add_node("hotel_chat", hotel_chat)
    graph_builder.add_node("tools", tool_node)
    graph_builder.add_edge(START, "memory_recall_hotel")
    graph_builder.add_edge("memory_recall_hotel", "hotel_chat")
    graph_builder.add_conditional_edges("hotel_chat", tools_condition)
    graph_builder.add_edge("tools", "hotel_chat")
    return graph_builder.compile(name="hotel_agent")
