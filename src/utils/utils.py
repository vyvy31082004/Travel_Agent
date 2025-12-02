from datetime import datetime,date
from pydantic import BaseModel
from langgraph.prebuilt import ToolNode
from langchain_core.runnables import RunnableLambda
from langchain_core.messages import ToolMessage
from typing import Optional

def current_time():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def to_date(date_string: str) -> Optional[date]:
    """Convert string to date object, trying multiple formats."""
    if isinstance(date_string, date):
        return date_string
    if not isinstance(date_string, str):
        return None
        
    formats_to_try = [
        "%d/%m/%Y",  # For user inputs like "dd/mm/yyyy"
        "%Y-%m-%d",  # For dates from database or ISO format
    ]
    
    for fmt in formats_to_try:
        try:
            return datetime.strptime(date_string.strip(), fmt).date()
        except (ValueError, TypeError):
            continue
            
    return None

def handle_tool_error(state) -> dict:
    error = state.get("error")
    tool_calls = state["messages"][-1].tool_calls
    return {
        "messages": [
            ToolMessage(
                content=f"Error: {repr(error)}\n please fix your mistakes.",
                tool_call_id=tc["id"],
            )
            for tc in tool_calls
        ]
    }

def create_tool_node_with_fallback(tools: list) -> dict:
    return ToolNode(tools).with_fallbacks(
        [RunnableLambda(handle_tool_error)], exception_key="error"
    )

class CompleteOrEscalate(BaseModel):
    """Công cụ để đánh dấu nhiệm vụ hiện tại là đã hoàn thành và/hoặc chuyển quyền kiểm soát hộp thoại cho primary agent."""
    cancel: bool = True
    reason: str