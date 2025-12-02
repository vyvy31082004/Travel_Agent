from typing import Annotated, Literal, Optional, List, Any, Dict 
from typing_extensions import TypedDict
from langgraph.graph.message import AnyMessage, add_messages

def update_dialog_stack(left: list[str], right: Optional[str]) -> list[str]:
    """Cập nhật stack trạng thái hội thoại. """
    if right is None:
        return left
    if right == "pop":
        return left[:-1]
    return left + [right]

class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    user_info: str
    dialog_state: Annotated[
        list[
            Literal[
                "primary_assistant",
                "multi_dispatch",
                # "flight_assistant",
                "car_rental_assistant",
                "hotel_assistant",
                "excursion_assistant",
            ]
        ],
        update_dialog_stack,
    ]
    tool_call_id: Optional[str]
    tool_queue: List[Dict[str, Any]]