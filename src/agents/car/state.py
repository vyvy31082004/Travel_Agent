from typing import Annotated, Any, Optional

from langgraph.graph.message import AnyMessage, add_messages
from typing_extensions import TypedDict


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
    user_id: Annotated[Optional[str], keep_latest]
    thread_id: Annotated[Optional[str], keep_latest]
    domain_memory_context: Annotated[Optional[str], keep_latest]
    domain_soft_memory_context: Annotated[Optional[str], keep_latest]
    domain_action: Annotated[Optional[str], keep_latest]
    recalled_memory_ids: Annotated[list[str], merge_unique_ids]
    memory_applicability: Annotated[list[dict], merge_branch_results]
    user_query: Annotated[Optional[str], keep_latest]
    delegated_request: Annotated[Optional[str], keep_latest]
    turn_constraints: Annotated[Optional[list[str]], keep_latest]
    requests: Annotated[dict[str, dict], merge_dicts]
    request_results: Annotated[dict[str, dict], merge_dicts]
    visible_results: Annotated[dict[str, dict], merge_dicts]
    selected_items: Annotated[dict[str, dict], merge_dicts]
    active_request_id: Annotated[Optional[str], keep_latest]
    latest_request_by_domain: Annotated[dict[str, str], merge_dicts]
