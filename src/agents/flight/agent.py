from langgraph.graph import StateGraph, START
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv
from langgraph.prebuilt import tools_condition
from langgraph.prebuilt import ToolNode
from agents.flight.tools import search_flights
from prompts.prompt import flight_prompts
from agents.flight.state import State

load_dotenv()

llm = ChatGoogleGenerativeAI(
    model = "gemini-2.5-flash",
    temperature = 0.2,
)

flight_tools = [search_flights]
flight_runnable = flight_prompts|llm.bind_tools(flight_tools )
tool_node = ToolNode(flight_tools)

def flight_chat(state: State):
    response = flight_runnable.invoke(state)
    if isinstance(response, list):
        return {"messages": response}
    return {"messages": [response]}

graph_builder = StateGraph(State)
graph_builder.add_node("flight_chat", flight_chat)
graph_builder.add_node("tools", tool_node)
graph_builder.add_edge(START, "flight_chat")
graph_builder.add_conditional_edges(
    "flight_chat",
    tools_condition,
)
graph_builder.add_edge("tools", "flight_chat")
flight_graph = graph_builder.compile()