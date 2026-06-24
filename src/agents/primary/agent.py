from langchain_core.runnables import RunnableConfig
from prompts.prompt import primary_prompts
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv
import warnings
from pydantic import BaseModel, Field
# from agents.flight.tools import search_flights, fetch_user_flight_information
from langchain_core.messages import ToolMessage, AIMessage
from agents.primary.state import State
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph, START, END
from langchain_core.runnables import RunnableLambda
from utils.utils import create_tool_node_with_fallback, CompleteOrEscalate
# from agents.flight.agent import flight_graph
from agents.car.agent import car_graph
from agents.hotel.agent import hotel_graph
from agents.excursion.agent import excursion_graph
from agents.flight.agent import flight_graph
from typing import Optional
warnings.filterwarnings("ignore")
load_dotenv()
 
# Primary chỉ trực tiếp xử lý search_flights; còn lại điều hướng qua agent con
# primary_tools = [search_flights, fetch_user_flight_information]
 
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature = 0.2,
)
 
def generic_assistant_entry(state: State, assistant_name: str, dialog_state: str) -> dict:
    tcid = state.get("tool_call_id")
    if not tcid:
        last_message = state["messages"][-1]
        tcid = (last_message.tool_calls[0]["id"]
                if getattr(last_message, "tool_calls", None) else None)
    if tcid:
        state["messages"].append(
            ToolMessage(
                content=(
                    f"The assistant is now the {assistant_name}. Reflect on the conversation above.\n"
                    f"ANSWERING RULES:\n"
                    f"- Answer ONLY within the scope of {assistant_name}.\n"
                    f"- Do NOT mention limitations or other domains (e.g., do not say you only handle hotels).\n"
                    f"- If you use a tool, you MUST use the exact output of the tool in your final response (especially numbers and prices).\n"
                    f"- Return concise, structured results. Prefer a single bullet list or a short JSON payload.\n"
                ),
                tool_call_id=tcid,
            )
        )
    state["dialog_state"] = dialog_state
    return state
 
# class ToFlightAssistant(BaseModel):
#     """Chuyển công việc cho flight agent để xử lý thông tin cập nhật và hủy chuyến bay."""
#     request: Optional[str] = Field(None, description="Any necessary followup questions the update flight assistant should clarify before proceeding.")
 
class ToCarRentalAssistant(BaseModel):
    """Chuyển công việc cho car agent để xử lý việc cập nhật/huỷ/đặt thuê xe."""
    # location: Optional[str] = Field(None, description="The location where the user wants to rent a car.")
    # start_date: Optional[str] = Field(None, description="The start date of the car rental.")
    # end_date: Optional[str] = Field(None, description="The end date of the car rental.")
    # request: Optional[str] = Field(None, description="Any additional information or requests from the user regarding the car rental.")
 
class ToHotelAssistant(BaseModel):
    """Chuyển công việc cho hotel agent để xử lý việc đặt hoặc huỷ phòng khách sạn."""
    # location: Optional[str] = Field(None, description="City or area")
    # checkin_date: Optional[str] = Field(None, description="YYYY-MM-DD")
    # checkout_date: Optional[str] = Field(None, description="YYYY-MM-DD")
    # request: Optional[str] = Field(None, description="Extra wishes/constraints")
 
class ToExcursionAssistant(BaseModel):
    """Chuyển công việc cho excursion agent để xử lý việc tìm thông tin cho các chuyến dã ngoại"""
        # location: Optional[str] = Field(None, description="The location where the user wants to book a recommended trip.")
        # request: Optional[str] = Field(None, description="Any additional information or requests from the user regarding the trip recommendation.")

class ToFlightAssistant(BaseModel):
    """Chuyển công việc cho flight agent để xử lý việc tìm thông tin cho các chuyến bay"""
        # departure_airport_code: Optional[str] = Field(None, description="The departure airport code.")
        # arrival_airport_code: Optional[str] = Field(None, description="The arrival airport code.")
        # departure_time: Optional[str] = Field(None, description="The departure time.")
        # arrival_time: Optional[str] = Field(None, description="The arrival time.")
        # city_depart: Optional[str] = Field(None, description="The departure city.")
        # city_arrive: Optional[str] = Field(None, description="The arrival city.")
        # flight_no: Optional[str] = Field(None, description="The flight number.")
        # request: Optional[str] = Field(None, description="Any additional information or requests from the user regarding the flight.")
 
# LLM + tool schemas
primary_runnable = primary_prompts | llm.bind_tools(
    [ ToCarRentalAssistant, ToHotelAssistant, ToExcursionAssistant, ToFlightAssistant]
)
 
def primary_chat(state: dict, config: RunnableConfig) -> dict:
    last = state["messages"][-1]
    # Nếu đã bơm tool_call từ queue → KHÔNG gọi LLM; router sẽ chuyển subgraph
    if getattr(last, "tool_calls", None):
        return {"messages": []}
    result = primary_runnable.invoke(state)
    # Nếu có nhiều tool call → giữ cái đầu, phần còn lại vào queue
    tcs = getattr(result, "tool_calls", None) or []
    queue = list(state.get("tool_queue", []))
    if len(tcs) > 1:
        result.tool_calls = [tcs[0]]
        queue.extend(tcs[1:])
    out = {"messages": [result]}
    if queue:
        out["tool_queue"] = queue
    return out
 
# LangGraph
builder = StateGraph(State)
 
# def user_info(state: State):
#     # return {"user_info": fetch_user_flight_information.invoke({})}
#     return {"user_info": "1234567890"}
 
# builder.add_node("fetch_user_info", user_info)

 
# Flight
# builder.add_node(
#     "flight_assistant",
#     RunnableLambda(lambda s: generic_assistant_entry(s, "Flight Updates & Booking Assistant", "flight_assistant")) | flight_graph
# )
# def route_update_flight(state: State) -> str:
#     tool_calls = state["messages"][-1].tool_calls
#     if tool_calls:
#         did_cancel = any(tc["name"] == CompleteOrEscalate.__name__ for tc in tool_calls)
#         if did_cancel:
#             return "leave_skill"
#         return "flight_assistant"
#     return "leave_skill"
# builder.add_edge("flight_assistant", "leave_skill")
 
# Car
builder.add_node(
    "car_rental_assistant",
    RunnableLambda(lambda s: generic_assistant_entry(s, "Car Rental Assistant", "car_rental_assistant")) | car_graph
)
def route_book_car_rental(state: State) -> str:
    tool_calls = state["messages"][-1].tool_calls
    if tool_calls:
        did_cancel = any(tc["name"] == CompleteOrEscalate.__name__ for tc in tool_calls)
        if did_cancel:
            return "leave_skill"
        return "car_rental_assistant"
    return "leave_skill"
builder.add_edge("car_rental_assistant", "leave_skill")
 
# Hotel
builder.add_node(
    "hotel_assistant",
    RunnableLambda(lambda s: generic_assistant_entry(s, "Hotel Booking Assistant", "hotel_assistant")) | hotel_graph
)
def route_book_hotel(state: State) -> str:
    tool_calls = state["messages"][-1].tool_calls
    if tool_calls:
        did_cancel = any(tc["name"] == CompleteOrEscalate.__name__ for tc in tool_calls)
        if did_cancel:
            return "leave_skill"
        return "hotel_assistant"
    return "leave_skill"
builder.add_edge("hotel_assistant", "leave_skill")
 
#Excursion
builder.add_node(
    "excursion_assistant",
    RunnableLambda(lambda s: generic_assistant_entry(s, "Trip Recommendation Assistant", "excursion_assistant")) | excursion_graph
)
def route_book_excursion(state: State):
    tool_calls = state["messages"][-1].tool_calls
    if tool_calls:
        did_cancel = any(tc["name"] == CompleteOrEscalate.__name__ for tc in tool_calls)
        if did_cancel:
            return "leave_skill"
        return "excursion_assistant"
    return "leave_skill"
builder.add_edge("excursion_assistant", "leave_skill")


#flight 
builder.add_node(
    "flight_assistant",
    RunnableLambda(lambda s: generic_assistant_entry(s, "Flight Booking Assistant", "flight_assistant")) | flight_graph
)
def route_book_flight(state: State):
    tool_calls = state["messages"][-1].tool_calls
    if tool_calls:
        did_cancel = any(tc["name"] == CompleteOrEscalate.__name__ for tc in tool_calls)
        if did_cancel:
            return "leave_skill"
        return "flight_assistant"
    return "leave_skill"
builder.add_edge("flight_assistant", "leave_skill")
 
def pop_dialog_state(state: State) -> dict:
    messages = []
    # Đóng tool-call đang active (nếu có)
    active_tcid = state.get("tool_call_id")
    if active_tcid:
        # Lấy message cuối cùng để làm nội dung phản hồi cho tool call
        last_message = state["messages"][-1]
        content = "Task completed."
        if hasattr(last_message, "content") and last_message.content:
            content = f"Result from assistant: {last_message.content}"
            
        messages.append(ToolMessage(
            content=content,
            tool_call_id=active_tcid,
        ))
        # Xóa để tránh tái kích hoạt
        state["tool_call_id"] = None

    queue = list(state.get("tool_queue", []))
    if queue:
        next_tc = queue.pop(0)
        messages.append(AIMessage(
            content=f"Proceeding with the next requested task via {next_tc['name']}.",
            tool_calls=[next_tc]
        ))
        return {"dialog_state": "pop", "messages": messages, "tool_queue": queue}
 
    return {"dialog_state": "pop", "messages": messages, "tool_queue": []}
 
# Router primary
def route_primary_assistant(state: State):
    tool_calls = getattr(state["messages"][-1], "tool_calls", None) or []
    if tool_calls:
        tc = tool_calls[0]
        state["tool_call_id"] = tc["id"]
        name = tc["name"]
        # if name == ToFlightAssistant.__name__:
        #     return "flight_assistant"
        if name == ToCarRentalAssistant.__name__:
            return "car_rental_assistant"
        if name == ToHotelAssistant.__name__:
            return "hotel_assistant"
        if name == ToExcursionAssistant.__name__:
            return "excursion_assistant"
        if name == ToFlightAssistant.__name__:
            return "flight_assistant"
        return "primary_tools"
    return END
 
# Leave-skill → quay lại primary
builder.add_node("leave_skill", pop_dialog_state)
builder.add_edge("leave_skill", "primary_assistant")
builder.add_node("primary_assistant", primary_chat)
builder.add_edge(START, "primary_assistant")
# builder.add_node("primary_tools", create_tool_node_with_fallback(primary_tools))
# builder.add_edge("primary_tools", "primary_assistant")
builder.add_conditional_edges(
    "primary_assistant",
    route_primary_assistant,
    ["car_rental_assistant", "hotel_assistant", "excursion_assistant", "flight_assistant", END],
)
#builder.add_edge("fetch_user_info", "primary_assistant")
 
memory = InMemorySaver()
primary_graph = builder.compile(checkpointer=memory)
