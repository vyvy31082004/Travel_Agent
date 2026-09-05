import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

from langchain_core.messages import HumanMessage, SystemMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memory.domain_runtime import invoke_domain_llm_with_temp_payloads


def test_soft_memory_prompt_requires_filter_or_tradeoff():
    captured_messages: list = []

    async def fake_invoke(state, config=None):
        captured_messages.extend(state.get("messages") or [])
        return {"messages": []}

    runnable = AsyncMock()
    runnable.ainvoke = fake_invoke

    state = {
        "messages": [HumanMessage(content="Tìm khách sạn Phú Quốc")],
        "domain_soft_memory_context": "Thích khách sạn yên tĩnh",
    }

    async def _run():
        await invoke_domain_llm_with_temp_payloads(
            runnable,
            state,
            config={},
            repo=None,
        )

    asyncio.run(_run())

    soft_messages = [
        message
        for message in captured_messages
        if isinstance(message, SystemMessage)
        and "Soft-priority domain memory" in str(message.content)
    ]
    assert len(soft_messages) == 1
    content = str(soft_messages[0].content)
    assert "no hard filters" not in content.lower()
    assert "trade-off" in content.lower()
    assert "FILTER" in content
