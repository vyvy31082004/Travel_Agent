from __future__ import annotations

from typing import Any, Literal, Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    RemoveMessage,
    ToolMessage,
)

KeepRoute = Literal["summarize_conversation", "__end__"]

KEEP_COUNT = 8  # ~2 handoff turns (Human→AI tool→Tool→AI final × 2)
MAX_MESSAGES = 12  # must be > KEEP_COUNT


def message_content_size(message: AnyMessage) -> int:
    content = getattr(message, "content", "") or ""
    return len(content if isinstance(content, str) else str(content))


def should_summarize(
    state: dict[str, Any],
    max_messages: int = MAX_MESSAGES,
    max_chars: int = 30_000,
    keep_count: int = KEEP_COUNT,
) -> KeepRoute:
    messages = state.get("messages") or []
    total_chars = sum(message_content_size(m) for m in messages)
    if len(messages) < max_messages and total_chars < max_chars:
        return "__end__"

    # Only route when there is a safe prefix to summarize+remove.
    # Avoids empty summarize nodes for a single long/heavy turn.
    if not select_messages_to_summarize(messages, keep_count=keep_count):
        return "__end__"
    return "summarize_conversation"


def _is_human(message: AnyMessage) -> bool:
    return isinstance(message, HumanMessage) or getattr(message, "type", None) == "human"


def _has_tool_calls(message: AnyMessage) -> bool:
    return bool(getattr(message, "tool_calls", None) or [])


def split_into_turns(messages: Sequence[AnyMessage]) -> list[list[AnyMessage]]:
    """Group messages into turns that start at each HumanMessage.

    A complete turn typically looks like:
    Human → AI(tool_call)? → Tool* → AI(final)?
    """
    turns: list[list[AnyMessage]] = []
    current: list[AnyMessage] = []
    for message in messages:
        if _is_human(message) and current:
            turns.append(current)
            current = [message]
        else:
            current.append(message)
    if current:
        turns.append(current)
    return turns


def find_keep_start(messages: Sequence[AnyMessage], keep_count: int) -> int:
    """Index where the kept window starts, aligned to a Human turn boundary.

    Prefer keeping about ``keep_count`` trailing messages, but never start mid-turn
    (e.g. on AI(tool_call) / Tool / AI(final)). Advance forward to the next Human
    so the removed prefix ends on a complete turn.
    """
    n = len(messages)
    if n <= keep_count or keep_count <= 0:
        return n

    start = n - keep_count
    if _is_human(messages[start]):
        return start

    # Candidate landed mid-turn — move forward to the next Human.
    for idx in range(start + 1, n):
        if _is_human(messages[idx]):
            return idx

    # No later Human: expand keep leftward to the Human that owns this turn.
    for idx in range(start, -1, -1):
        if _is_human(messages[idx]):
            return idx
    return 0


def choose_complete_turns(messages: Sequence[AnyMessage]) -> list[AnyMessage]:
    """Drop trailing incomplete tool-call chains from a removal window.

    Safety net so we never summarize/remove a lone AI(tool_call) or Tool
    without its matching pair still present in the same window.
    """
    old = list(messages)
    while old:
        last = old[-1]
        if isinstance(last, AIMessage) and _has_tool_calls(last):
            old.pop()
            continue

        if isinstance(last, ToolMessage):
            has_parent = False
            for prior in reversed(old[:-1]):
                if isinstance(prior, AIMessage) and _has_tool_calls(prior):
                    has_parent = True
                    break
                if _is_human(prior):
                    break
            if not has_parent:
                old.pop()
                continue
        break
    return old


def select_messages_to_summarize(
    messages: Sequence[AnyMessage],
    keep_count: int = KEEP_COUNT,
) -> list[AnyMessage]:
    """Return old messages safe to summarize+remove (complete turns only)."""
    messages = list(messages)
    if len(messages) <= keep_count:
        return []

    start = find_keep_start(messages, keep_count)
    if start <= 0:
        return []

    return choose_complete_turns(messages[:start])


def _message_text(message: Any) -> str:
    if message is None:
        return ""
    
    # Handle message objects
    content = getattr(message, "content", message)
    
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text")
                if text:
                    parts.append(str(text))
            else:
                text = getattr(block, "text", None)
                if text:
                    parts.append(str(text))
        return "\n".join(parts).strip()
    
    # If it's still an object or other type, try str()
    if content == message:
        return str(content).strip()
    
    return _message_text(content)


async def summarize_conversation(
    state: dict[str, Any],
    llm: BaseChatModel,
    keep_count: int = KEEP_COUNT,
) -> dict[str, Any]:
    messages = list(state.get("messages") or [])
    old_messages = select_messages_to_summarize(messages, keep_count=keep_count)
    if not old_messages:
        return {}

    prompt = (
        "Bản tóm tắt hiện tại:\n"
        f"{state.get('summary') or '(Chưa có)'}\n\n"
        "Hãy cập nhật bản tóm tắt trên bằng cách tích hợp các tin nhắn mới dưới đây.\n"
        "Yêu cầu:\n"
        "1. Giữ lại các thông tin quan trọng: yêu cầu của người dùng, ngày tháng, địa điểm, các lựa chọn đã chốt hoặc đã từ chối.\n"
        "2. KHÔNG sao chép danh sách kết quả API dài, chỉ tóm tắt các điểm chính (vd: 'đã tìm thấy 10 khách sạn').\n"
        "3. Trả lời bằng tiếng Việt, ngắn gọn và súc tích.\n"
    )
    
    # Pre-process messages to plain text to be safer with various LLM models
    formatted_messages = []
    for m in old_messages:
        role = "Người dùng" if _is_human(m) else "Trợ lý"
        text = _message_text(m)
        if text:
            formatted_messages.append(HumanMessage(content=f"{role}: {text}"))
        elif isinstance(m, AIMessage) and _has_tool_calls(m):
            formatted_messages.append(HumanMessage(content=f"{role}: (Đang gọi công cụ...)"))

    if not formatted_messages:
        return {}

    result = await llm.ainvoke([HumanMessage(content=prompt), *formatted_messages])
    summary_text = _message_text(getattr(result, "content", result))
    
    # Never drop history unless we actually got a usable summary.
    if not summary_text or len(summary_text) < 5:
        return {}

    removals = [
        RemoveMessage(id=m.id)
        for m in old_messages
        if getattr(m, "id", None)
    ]
    return {
        "summary": summary_text,
        "messages": removals,
    }
