from typing import Annotated, Any, Dict, Literal, Optional

from langgraph.graph.message import AnyMessage, add_messages
from typing_extensions import TypedDict


def update_dialog_stack(left: list[str], right: Optional[str]) -> list[str]:
    """Cập nhật stack trạng thái hội thoại."""
    if right is None:
        return left
    if right == "pop":
        return left[:-1]
    return left + [right]


def merge_dicts(left: dict, right: Optional[dict]) -> dict:
    if right is None:
        return left
    return {**left, **right}


def keep_latest(left: Any, right: Any) -> Any:
    return right if right is not None else left


class State(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    user_info: str
    dialog_state: Annotated[
        list[
            Literal[
                "primary_assistant",
                "multi_dispatch",
                "flight_assistant",
                "hotel_assistant",
                "excursion_assistant",
                "car_assistant",
                "travel_planner_assistant",
            ]
        ],
        update_dialog_stack,
    ]
    tool_call_id: Annotated[Optional[str], keep_latest]
    active_assistant: Annotated[Optional[str], keep_latest]
    flight_token_map: Annotated[Dict[str, Any], merge_dicts]
