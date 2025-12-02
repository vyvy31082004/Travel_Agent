from langgraph.graph.message import AnyMessage, add_messages
from typing_extensions import TypedDict
from typing import Annotated

class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]