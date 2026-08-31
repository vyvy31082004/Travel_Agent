from langchain_core.runnables import RunnableConfig
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from dotenv import load_dotenv

from agents.excursion.state import State
from agents.excursion.tools import get_excursion_tools
from memory.agent_helpers import domain_chat_with_memory
from memory.long_term import MemoryDomain
from memory.recall_nodes import make_domain_memory_recall_node
from memory.tool_wrapper import wrap_tools_with_result_store
from prompts.prompt import excursion_prompts
from repositories.result_store import ResultStoreRepository
from services.long_term_memory import MemoryService
from utils.tracing import with_trace_config

load_dotenv()

llm = ChatGoogleGenerativeAI(
    model="gemini-3.6-flash",
)


async def build_excursion_graph(
    *,
    repo: ResultStoreRepository | None = None,
    memory_service: MemoryService | None = None,
):
    excursion_tools = await get_excursion_tools()
    if repo is not None:
        excursion_tools = wrap_tools_with_result_store(excursion_tools, repo)

    excursion_runnable = (
        excursion_prompts | llm.bind_tools(excursion_tools)
    ).with_config(
        with_trace_config(
            run_name="excursion_llm",
            tags=["customer-support", "excursion", "llm"],
            metadata={"agent": "excursion"},
        )
    )
    tool_node = ToolNode(excursion_tools).with_config(
        with_trace_config(
            run_name="excursion_tools",
            tags=["customer-support", "excursion", "tools", "mcp"],
            metadata={"agent": "excursion", "tool_transport": "mcp_sse"},
        )
    )

    async def excursion_chat(state: dict, config: RunnableConfig):
        return await domain_chat_with_memory(
            runnable=excursion_runnable,
            state=state,
            config=config,
            domain_hint="tour",
            repo=repo,
        )

    graph_builder = StateGraph(State)
    graph_builder.add_node(
        "memory_recall_excursion",
        make_domain_memory_recall_node(
            memory_service,
            domain=MemoryDomain.EXCURSION,
            llm=llm,
            node_name="memory_recall_excursion",
        ),
    )
    graph_builder.add_node("excursion_chat", excursion_chat)
    graph_builder.add_node("tools", tool_node)
    graph_builder.add_edge(START, "memory_recall_excursion")
    graph_builder.add_edge("memory_recall_excursion", "excursion_chat")
    graph_builder.add_conditional_edges("excursion_chat", tools_condition)
    graph_builder.add_edge("tools", "excursion_chat")
    return graph_builder.compile(name="excursion_agent")
