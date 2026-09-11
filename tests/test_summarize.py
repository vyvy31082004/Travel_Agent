from __future__ import annotations

import sys
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from services.summarize import (
    choose_complete_turns,
    e2e_summarize_all_enabled,
    should_summarize,
)


def test_e2e_summarize_all_enabled_reads_configurable() -> None:
    assert e2e_summarize_all_enabled(None) is False
    assert e2e_summarize_all_enabled({"configurable": {}}) is False
    assert e2e_summarize_all_enabled({"configurable": {"e2e_summarize_all": True}}) is True


def test_should_summarize_short_history_stays_end() -> None:
    state = {
        "messages": [
            HumanMessage(content="Tôi định ở Đà Nẵng."),
            AIMessage(content="Bạn muốn ở ngày nào?"),
        ]
    }
    assert should_summarize(state) == "__end__"


def test_should_summarize_e2e_flag_routes_to_summarize() -> None:
    state = {
        "messages": [
            HumanMessage(content="Tôi định ở Đà Nẵng."),
            AIMessage(content="Bạn muốn ở ngày nào?"),
            HumanMessage(content="Từ 10 đến 12/10, 2 người."),
            AIMessage(content="Ok, mình ghi nhận."),
        ]
    }
    config = {"configurable": {"e2e_summarize_all": True}}
    assert should_summarize(state, config=config) == "summarize_conversation"


def test_should_summarize_e2e_flag_empty_stays_end() -> None:
    config = {"configurable": {"e2e_summarize_all": True}}
    assert should_summarize({"messages": []}, config=config) == "__end__"


def test_choose_complete_turns_keeps_finished_exchange() -> None:
    messages = [
        HumanMessage(content="T1"),
        AIMessage(content="ack"),
        HumanMessage(content="T2"),
        AIMessage(content="ack 2"),
    ]
    kept = choose_complete_turns(messages)
    assert len(kept) == 4
