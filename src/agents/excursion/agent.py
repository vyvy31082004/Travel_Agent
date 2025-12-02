from langgraph.graph import StateGraph, START
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv
from langgraph.prebuilt import tools_condition
from langgraph.prebuilt import ToolNode
from agents.excursion.tools import search_trip, book_excursion , cancel_tour, update_tour 
from prompts.prompt import excursion_prompts
from agents.excursion.state import State

load_dotenv()

llm = ChatGoogleGenerativeAI(
    model = "gemini-2.5-flash",
    temperature = 0.2,
)

excursion_tools = [search_trip, book_excursion, cancel_tour, update_tour]
excursion_runnable = excursion_prompts|llm.bind_tools(excursion_tools )
tool_node = ToolNode(excursion_tools)

def excursion_chat(state: State):
    response = excursion_runnable.invoke(state)
    if isinstance(response, list):
        return {"messages": response}
    return {"messages": [response]}

graph_builder = StateGraph(State)
graph_builder.add_node("excursion_chat", excursion_chat)
graph_builder.add_node("tools", tool_node)
graph_builder.add_edge(START, "excursion_chat")
graph_builder.add_conditional_edges(
    "excursion_chat",
    tools_condition,
)
graph_builder.add_edge("tools", "excursion_chat")
excursion_graph = graph_builder.compile()