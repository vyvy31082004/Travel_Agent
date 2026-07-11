from langgraph.graph.message import AnyMessage, add_messages
from typing_extensions import TypedDict
from typing import Annotated


def _merge_dicts(a: dict, b: dict) -> dict:
    return {**a, **b}


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    flight_token_map: Annotated[dict, _merge_dicts]
