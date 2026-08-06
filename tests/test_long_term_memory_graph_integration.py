from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_primary_graph_has_recall_before_primary_and_finalize_before_end():
    source = (ROOT / "src" / "agents" / "primary" / "agent.py").read_text(
        encoding="utf-8"
    )
    assert 'builder.add_node("memory_recall"' in source
    assert 'builder.add_edge(START, "memory_recall")' in source
    assert 'builder.add_edge("memory_recall", "primary_assistant")' in source
    assert '"__end__": "memory_finalize"' in source
    assert 'builder.add_edge("memory_finalize", END)' in source


def test_primary_prompt_separates_summary_memory_and_tool_results():
    source = (ROOT / "src" / "agents" / "primary" / "agent.py").read_text(
        encoding="utf-8"
    )
    assert "Bản tóm tắt hội thoại" in source
    assert "Long-term user memory recalled across conversations" in source
    assert "temporary tool results" in source


def test_chat_route_contract_remains_compatible():
    source = (ROOT / "src" / "app.py").read_text(encoding="utf-8")
    assert "class ChatRequest" in source
    assert "msg: str" in source
    assert "thread_id: str | None" in source
    assert "user_id: str | None" in source
    assert 'return {"response": response, "thread_id": thread_id, "user_id": user_id}' in source
