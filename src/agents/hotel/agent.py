from langgraph.graph import StateGraph, START
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv
from langgraph.prebuilt import tools_condition
from langgraph.prebuilt import ToolNode
from agents.hotel.tools import search_hotels, search_hotel_rooms, book_hotel_room, update_hotel_booking, cancel_hotel_booking
from prompts.prompt import hotel_prompts
from agents.hotel.state import State

load_dotenv()

llm = ChatGoogleGenerativeAI(
model = "gemini-2.5-flash",
temperature = 0.2,
)

hotel_tools = [search_hotels, search_hotel_rooms, book_hotel_room, update_hotel_booking, cancel_hotel_booking]
hotel_runnable = hotel_prompts| llm.bind_tools(hotel_tools)
tool_node = ToolNode(hotel_tools)

def hotel_chat(state: dict):
    response = hotel_runnable.invoke(state)
    if isinstance(response, list):
        return {"messages": response}
    return {"messages": [response]}

graph_builder = StateGraph(State)
graph_builder.add_node("hotel_chat", hotel_chat)
graph_builder.add_node("tools", tool_node)
graph_builder.add_edge(START, "hotel_chat")
graph_builder.add_conditional_edges(
    "hotel_chat",
    tools_condition,
)
graph_builder.add_edge("tools", "hotel_chat")
hotel_graph = graph_builder.compile()

