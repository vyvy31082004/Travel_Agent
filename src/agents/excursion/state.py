from typing import Annotated, Any, Optional

from langgraph.graph.message import AnyMessage, add_messages
from typing_extensions import TypedDict


def merge_dicts(left: Optional[dict], right: Optional[dict]) -> dict:
    if right is None:
        return left or {}
    return {**(left or {}), **right}


def keep_latest(left: Any, right: Any) -> Any:
    return right if right is not None else left


class State(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    summary: Annotated[Optional[str], keep_latest]
    user_id: Annotated[Optional[str], keep_latest]
    thread_id: Annotated[Optional[str], keep_latest]
    requests: Annotated[dict[str, dict], merge_dicts]
    request_results: Annotated[dict[str, dict], merge_dicts]
    visible_results: Annotated[dict[str, dict], merge_dicts]
    selected_items: Annotated[dict[str, dict], merge_dicts]
    active_request_id: Annotated[Optional[str], keep_latest]
    latest_request_by_domain: Annotated[dict[str, str], merge_dicts]
