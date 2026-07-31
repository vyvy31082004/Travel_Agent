from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from services.summarize import (
    KEEP_COUNT,
    MAX_MESSAGES,
    find_keep_start,
    select_messages_to_summarize,
    should_summarize,
    split_into_turns,
)


def _ai_tool(name: str, call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": {"request": "x"}, "id": call_id, "type": "tool_call"}],
        id=f"ai-{call_id}",
    )


def _tool(call_id: str, text: str = "ok") -> ToolMessage:
    return ToolMessage(content=text, tool_call_id=call_id, id=f"tool-{call_id}")


def _final(text: str, msg_id: str) -> AIMessage:
    return AIMessage(content=text, id=msg_id)


def _human(text: str, msg_id: str) -> HumanMessage:
    return HumanMessage(content=text, id=msg_id)


def test_split_into_turns_groups_by_human():
    messages = [
        _human("hotel", "h1"),
        _ai_tool("ToHotelAssistant", "c1"),
        _tool("c1", "hotels"),
        _final("list hotels", "a1"),
        _human("reviews #3", "h2"),
        _ai_tool("ToHotelAssistant", "c2"),
        _tool("c2", "reviews"),
        _final("list reviews", "a2"),
        _human("flights", "h3"),
    ]
    turns = split_into_turns(messages)
    assert len(turns) == 3
    assert turns[0][0].content == "hotel"
    assert turns[1][0].content == "reviews #3"
    assert turns[2][0].content == "flights"


def test_find_keep_start_does_not_cut_mid_turn():
    messages = [
        _human("hotel", "h1"),
        _ai_tool("ToHotelAssistant", "c1"),
        _tool("c1", "hotels"),
        _final("list hotels", "a1"),
        _human("reviews #3", "h2"),
        _ai_tool("ToHotelAssistant", "c2"),
        _tool("c2", "reviews"),
        _final("list reviews", "a2"),
        _human("flights", "h3"),
    ]
    # Naive keep_count=6 would start at index 3 (AI final) — must advance to Human.
    start = find_keep_start(messages, keep_count=6)
    assert start == 4
    assert messages[start].content == "reviews #3"


def test_select_messages_to_summarize_removes_complete_turns_only():
    messages = [
        _human("hotel", "h1"),
        _ai_tool("ToHotelAssistant", "c1"),
        _tool("c1", "hotels"),
        _final("list hotels", "a1"),
        _human("reviews #3", "h2"),
        _ai_tool("ToHotelAssistant", "c2"),
        _tool("c2", "reviews"),
        _final("list reviews", "a2"),
        _human("flights", "h3"),
    ]
    old = select_messages_to_summarize(messages, keep_count=6)
    assert [m.id for m in old] == ["h1", "ai-c1", "tool-c1", "a1"]

    old_ids = {m.id for m in old}
    kept = [m for m in messages if m.id not in old_ids]
    assert _is_valid_gemini_tool_history(kept)


def test_select_messages_small_history_removes_nothing():
    messages = [
        _human("hotel", "h1"),
        _ai_tool("ToHotelAssistant", "c1"),
        _tool("c1", "hotels"),
        _final("list hotels", "a1"),
    ]
    assert select_messages_to_summarize(messages, keep_count=6) == []


def test_kept_window_never_starts_with_tool_or_orphan_ai_tool_call():
    messages = [
        _human("a", "h1"),
        _ai_tool("ToHotelAssistant", "c1"),
        _tool("c1"),
        _final("done a", "a1"),
        _human("b", "h2"),
        _ai_tool("ToFlightAssistant", "c2"),
        _tool("c2"),
        _final("done b", "a2"),
    ]
    for keep_count in range(1, len(messages) + 1):
        old = select_messages_to_summarize(messages, keep_count=keep_count)
        old_ids = {m.id for m in old}
        kept = [m for m in messages if m.id not in old_ids]
        assert _is_valid_gemini_tool_history(kept), (
            keep_count,
            [type(m).__name__ for m in kept],
        )


def test_should_summarize_three_complete_turns():
    """With KEEP=8 / MAX=12, summarize after ~3 handoff turns."""
    messages = [
        _human("hotel", "h1"),
        _ai_tool("ToHotelAssistant", "c1"),
        _tool("c1", "hotels"),
        _final("list hotels", "a1"),
        _human("tours", "h2"),
        _ai_tool("ToExcursionAssistant", "c2"),
        _tool("c2", "tours"),
        _final("list tours", "a2"),
        _human("reviews #2", "h3"),
        _ai_tool("ToExcursionAssistant", "c3"),
        _tool("c3", "reviews"),
        _final("list reviews", "a3"),
    ]
    assert len(messages) >= MAX_MESSAGES
    old = select_messages_to_summarize(messages, keep_count=KEEP_COUNT)
    assert [m.id for m in old] == ["h1", "ai-c1", "tool-c1", "a1"]
    assert should_summarize({"messages": messages}) == "summarize_conversation"


def test_should_summarize_skips_two_turns_under_max():
    messages = [
        _human("hotel", "h1"),
        _ai_tool("ToHotelAssistant", "c1"),
        _tool("c1", "hotels"),
        _final("list hotels", "a1"),
        _human("tours", "h2"),
        _ai_tool("ToExcursionAssistant", "c2"),
        _tool("c2", "tours"),
        _final("list tours", "a2"),
    ]
    assert len(messages) < MAX_MESSAGES
    assert should_summarize({"messages": messages}) == "__end__"


def test_should_summarize_skips_single_heavy_turn():
    """max_chars alone must not route when nothing can be removed."""
    messages = [
        _human("hotel", "h1"),
        _ai_tool("ToHotelAssistant", "c1"),
        _tool("c1", "x" * 35_000),
        _final("list hotels", "a1"),
    ]
    assert select_messages_to_summarize(messages, keep_count=KEEP_COUNT) == []
    assert should_summarize({"messages": messages}) == "__end__"


def test_should_summarize_skips_single_long_multi_tool_turn():
    """One Human + many tools can hit length but has no removable prefix."""
    messages = [
        _human("plan trip", "h1"),
        _ai_tool("get_weather", "c1"),
        _tool("c1", "weather"),
        _ai_tool("search_hotels", "c2"),
        _tool("c2", "hotels"),
        _ai_tool("search_attractions", "c3"),
        _tool("c3", "tours"),
        _ai_tool("search_flights", "c4"),
        _tool("c4", "flights"),
        _ai_tool("search_cars", "c5"),
        _tool("c5", "cars"),
        _final("itinerary", "a1"),
    ]
    assert len(messages) >= MAX_MESSAGES
    assert select_messages_to_summarize(messages, keep_count=KEEP_COUNT) == []
    assert should_summarize({"messages": messages}) == "__end__"


def _is_valid_gemini_tool_history(messages: list) -> bool:
    """Approximate Gemini rule: tool_call only after human or tool response."""
    pending_tool_ids: set[str] = set()
    last_kind = "start"
    for message in messages:
        if isinstance(message, HumanMessage):
            if pending_tool_ids:
                return False
            last_kind = "human"
            continue
        if isinstance(message, AIMessage) and _has_tool_calls(message):
            if last_kind not in {"human", "tool"}:
                return False
            pending_tool_ids = {tc["id"] for tc in message.tool_calls}
            last_kind = "ai_tools"
            continue
        if isinstance(message, ToolMessage):
            if message.tool_call_id not in pending_tool_ids and last_kind not in {
                "ai_tools",
                "tool",
            }:
                return False
            pending_tool_ids.discard(message.tool_call_id)
            last_kind = "tool"
            continue
        if isinstance(message, AIMessage):
            if pending_tool_ids:
                return False
            last_kind = "ai"
            continue
        return False
    return True


def _has_tool_calls(message: AIMessage) -> bool:
    return bool(getattr(message, "tool_calls", None) or [])
