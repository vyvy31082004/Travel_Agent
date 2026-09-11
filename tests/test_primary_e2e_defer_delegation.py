from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from agents.primary.agent import route_primary_assistant


def test_route_primary_defers_domain_send_when_e2e_summarize_all() -> None:
    state = {
        "messages": [
            SimpleNamespace(
                tool_calls=[
                    {
                        "id": "tc1",
                        "name": "ToFlightAssistant",
                        "args": {"request": "Bay ngày 12/10, 1 người"},
                    }
                ]
            )
        ]
    }
    config = {"configurable": {"e2e_summarize_all": True}}
    # Even if the model emitted a delegation tool call, do not fan out.
    assert route_primary_assistant(state, config) in {
        "summarize_conversation",
        "__end__",
    }
