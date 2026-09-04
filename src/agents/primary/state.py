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


def merge_dicts(left: Optional[dict], right: Optional[dict]) -> dict:
    if right is None:
        return left or {}
    return {**(left or {}), **right}


def keep_latest(left: Any, right: Any) -> Any:
    return right if right is not None else left


def merge_branch_results(
    left: list[dict], right: list[dict] | dict | None
) -> list[dict]:
    if right is None:
        return left or []
    items = right if isinstance(right, list) else [right]
    return (left or []) + items


def merge_unique_ids(left: list[str], right: list[str] | None) -> list[str]:
    if not right:
        return left or []
    return list(dict.fromkeys((left or []) + right))


class State(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    summary: Annotated[Optional[str], keep_latest]

    user_info: str
    user_id: Annotated[Optional[str], keep_latest]
    thread_id: Annotated[Optional[str], keep_latest]
    memory_context: Annotated[Optional[str], keep_latest]
    recalled_memory_ids: Annotated[list[str], merge_unique_ids]
    domain_branch_results: Annotated[list[dict], merge_branch_results]
    memory_job_id: Annotated[Optional[str], keep_latest]

    dialog_state: Annotated[
        list[
            Literal[
                "primary_assistant",
                "multi_dispatch",
                "flight_assistant",
                "hotel_assistant",
                "excursion_assistant",
                "car_assistant",
            ]
        ],
        update_dialog_stack,
    ]
    tool_call_id: Annotated[Optional[str], keep_latest]
    active_assistant: Annotated[Optional[str], keep_latest]
    flight_token_map: Annotated[Dict[str, Any], merge_dicts]

    # Structured short-term memory (refs only; payloads live in Result Store)
    trips: Annotated[dict[str, dict], merge_dicts]
    requests: Annotated[dict[str, dict], merge_dicts]
    request_results: Annotated[dict[str, dict], merge_dicts]
    visible_results: Annotated[dict[str, dict], merge_dicts]
    selected_items: Annotated[dict[str, dict], merge_dicts]
    active_request_id: Annotated[Optional[str], keep_latest]
    latest_request_by_domain: Annotated[dict[str, str], merge_dicts]
    pending_action: Annotated[Optional[dict], keep_latest]
    pending_clarification: Annotated[Optional[dict], keep_latest]

    delegated_request: Annotated[Optional[str], keep_latest]
    turn_constraints: Annotated[Optional[list[str]], keep_latest]
    trip_plan_user_message: Annotated[Optional[str], keep_latest]
    user_query: Annotated[Optional[str], keep_latest]
    domain_action: Annotated[Optional[str], keep_latest]
    domain_memory_context: Annotated[Optional[str], keep_latest]
    domain_soft_memory_context: Annotated[Optional[str], keep_latest]
    memory_applicability: Annotated[list[dict], merge_branch_results]
