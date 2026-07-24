# from langgraph.graph import StateGraph, START
# from langchain_google_genai import ChatGoogleGenerativeAI
# from dotenv import load_dotenv
# from langgraph.prebuilt import tools_condition
# from langgraph.prebuilt import ToolNode
# from agents.car.tools import search_car_rentals, search_cars, book_car_rental, update_car_rental, cancel_car_rental 
# from prompts.prompt import car_prompts
# from agents.car.state import State

# load_dotenv()

# llm = ChatGoogleGenerativeAI(
#     model="gemini-2.5-flash",
#     temperature = 0.2,
# )

# car_tools = [search_car_rentals, search_cars, book_car_rental, update_car_rental, cancel_car_rental]
# car_runnable = car_prompts| llm.bind_tools(car_tools)
# tool_node = ToolNode(car_tools)

# def car_chat(state: dict):
#     response = car_runnable.invoke(state)
#     if isinstance(response, list):
#         return {"messages": response}
#     return {"messages": [response]}
    
# graph_builder = StateGraph(State)
# graph_builder.add_node("car_chat", car_chat)
# graph_builder.add_node("tools", tool_node)
# graph_builder.add_edge(START, "car_chat")
# graph_builder.add_conditional_edges(
#     "car_chat",
#     tools_condition,
# )
# graph_builder.add_edge("tools", "car_chat")
# car_graph = graph_builder.compile()

from langgraph.graph import StateGraph, START
from langchain_core.runnables import RunnableConfig
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv
from langgraph.prebuilt import tools_condition
from langgraph.prebuilt import ToolNode
from agents.car.tools import get_car_tools
from prompts.prompt import car_prompts
from agents.car.state import State
from utils.tracing import with_trace_config
load_dotenv()
llm = ChatGoogleGenerativeAI(
model="gemini-2.5-flash",
temperature = 0.2,
)
async def build_car_graph():
    car_tools = await get_car_tools()   
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
        response = await car_runnable.ainvoke(
            state,
            config=with_trace_config(
                config,
                run_name="car_chat",
                tags=["customer-support", "car"],
                metadata={"agent": "car"},
            ),
        )
        if isinstance(response, list):
            return {"messages": response}
        return {"messages": [response]}

    graph_builder = StateGraph(State)
    graph_builder.add_node("car_chat", car_chat)
    graph_builder.add_node("tools", tool_node)
    graph_builder.add_edge(START, "car_chat")
    graph_builder.add_conditional_edges("car_chat", tools_condition)
    graph_builder.add_edge("tools", "car_chat")
    return graph_builder.compile(name="car_agent")