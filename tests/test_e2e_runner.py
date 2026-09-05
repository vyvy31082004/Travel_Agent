from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from e2e_eval.runner import _coerce_update_chunk, build_graph_turn_config


def test_graph_turn_config_does_not_set_metadata_run_id() -> None:
    config = build_graph_turn_config(
        thread_id="thread-1",
        user_id="user-1",
        case_id="e2e_summary_hotel_001",
        e2e_run_id="abc123",
        turn=2,
        summarize_all=True,
        collector=None,
    )
    metadata = config.get("metadata") or {}
    assert "run_id" not in metadata
    assert metadata["e2e_run_id"] == "abc123"
    assert metadata["turn"] == 2
    assert config["configurable"]["e2e_summarize_all"] is True
    assert config["configurable"]["thread_id"] == "thread-1"


def test_graph_turn_config_omits_summarize_when_false() -> None:
    config = build_graph_turn_config(
        thread_id="thread-1",
        user_id="user-1",
        case_id="e2e_tools_all_001",
        e2e_run_id="abc123",
        turn=7,
        summarize_all=False,
        collector=None,
    )
    assert "e2e_summarize_all" not in config["configurable"]


def test_coerce_update_chunk_accepts_dict_and_tuples() -> None:
    assert _coerce_update_chunk({"primary_assistant": {"x": 1}}) == {
        "primary_assistant": {"x": 1}
    }
    assert _coerce_update_chunk(("updates", {"join_results": {}})) == {
        "join_results": {}
    }
    assert _coerce_update_chunk(("values", {"messages": []})) == {}
    assert _coerce_update_chunk(("ns", {"hotel_chat": {}})) == {"hotel_chat": {}}
