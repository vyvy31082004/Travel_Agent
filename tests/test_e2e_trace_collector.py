from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from e2e_eval.trace_collector import TraceCollector, _iter_domain_branches


def test_scored_turn_delegation_ignores_history_and_search_tools():
    collector = TraceCollector(
        case_id="case-1",
        run_id="run-1",
        user_id="user-1",
        thread_id="thread-1",
        fixture_to_uuid={},
        input_messages=["hotel first", "flight now"],
    )
    messages = [
        HumanMessage(content="hotel first"),
        AIMessage(
            content="",
            tool_calls=[{
                "name": "ToHotelAssistant",
                "args": {},
                "id": "old-delegation",
                "type": "tool_call",
            }],
        ),
    ]
    collector.begin_scored_turn(message_start=len(messages))
    messages.extend([
        HumanMessage(content="flight now"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "ToFlightAssistant",
                    "args": {},
                    "id": "new-delegation",
                    "type": "tool_call",
                },
                {
                    "name": "search_one_way_flights_tool",
                    "args": {"origin": "SGN", "destination": "DAD"},
                    "id": "search-call",
                    "type": "tool_call",
                },
            ],
        ),
    ])

    trace = collector.finalize_trace(
        final_state={"messages": messages},
        final_answer="done",
    )

    assert trace["primary_route"]["delegated_domains"] == ["flight"]
    assert [
        call["name"]
        for call in trace["primary_route"]["delegation_tool_calls"]
    ] == ["ToFlightAssistant"]


def test_iter_domain_branches_skips_reset_marker():
    assert _iter_domain_branches({"__reset__": True}) == []
    assert _iter_domain_branches([{"__reset__": True}, "hotel"]) == []
    branch = {"domain": "hotel", "summary": "ok"}
    assert _iter_domain_branches(branch) == [branch]
    assert _iter_domain_branches([branch, {"__reset__": True}]) == [branch]


def test_record_node_update_ignores_reset_branch_results():
    collector = TraceCollector(
        case_id="case-1",
        run_id="run-1",
        user_id="user-1",
        thread_id="thread-1",
        fixture_to_uuid={},
        input_messages=["find hotel"],
    )
    # Streamed update from memory_recall_global_with_reset
    collector.record_node_update(
        "memory_recall_global",
        {
            "memory_context": "profile",
            "recalled_memory_ids": [],
            "domain_branch_results": {"__reset__": True},
        },
    )
    assert collector.trace["sub_agents"] == []
    assert collector.trace["global_recall"]["memory_context"] == "profile"

    collector.record_node_update(
        "join_results",
        {
            "domain_branch_results": [
                {"domain": "hotel", "summary": "found", "memory_applicability": []},
            ]
        },
    )
    assert collector.trace["join"]["merged_domains"] == ["hotel"]
    assert [item["domain"] for item in collector.trace["sub_agents"]] == ["hotel"]


def test_finalize_trace_ignores_reset_in_final_state():
    collector = TraceCollector(
        case_id="case-1",
        run_id="run-1",
        user_id="user-1",
        thread_id="thread-1",
        fixture_to_uuid={},
        input_messages=["find hotel"],
    )
    trace = collector.finalize_trace(
        final_state={
            "messages": [HumanMessage(content="find hotel")],
            "domain_branch_results": {"__reset__": True},
        },
        final_answer="done",
    )
    assert trace["sub_agents"] == []
    assert trace["join"]["branch_count"] in (0, None) or not trace["join"].get("merged_domains")


def test_finalize_merges_detail_tools_from_execution_path():
    collector = TraceCollector(
        case_id="case-1",
        run_id="run-1",
        user_id="user-1",
        thread_id="thread-1",
        fixture_to_uuid={},
        input_messages=["find hotel then rooms"],
    )
    collector.record_execution_step(
        "search_hotels_tool",
        graph="hotel_assistant",
        domain="hotel",
        tools=[
            {
                "name": "search_hotels_tool",
                "arguments": {"location": "Da Nang", "checkin_date": "2026-10-10"},
            }
        ],
        parent_chat_node="hotel_chat",
    )
    collector.record_execution_step(
        "get_hotel_room_list_tool",
        graph="hotel_assistant",
        domain="hotel",
        tools=[
            {
                "name": "get_hotel_room_list_tool",
                "arguments": {
                    "hotel_id": "16256042",
                    "checkin_date": "2026-10-10",
                    "checkout_date": "2026-10-12",
                },
            }
        ],
        parent_chat_node="hotel_chat",
    )
    collector.record_execution_step(
        "tools",
        graph="hotel_assistant",
        domain="hotel",
        tools=[
            {"name": "get_hotel_facility_tool", "arguments": {"hotel_id": "16256042"}},
            {"name": "get_hotel_policy_tool", "arguments": {"hotel_id": "16256042"}},
        ],
        parent_chat_node="hotel_chat",
    )

    trace = collector.finalize_trace(
        final_state={"messages": [HumanMessage(content="find hotel then rooms")]},
        final_answer="done",
    )
    names = [entry["name"] for entry in trace["tools"]]
    assert "search_hotels_tool" in names
    assert "get_hotel_room_list_tool" in names
    assert "get_hotel_facility_tool" in names
    assert "get_hotel_policy_tool" in names
    room = next(e for e in trace["tools"] if e["name"] == "get_hotel_room_list_tool")
    assert room["arguments"]["hotel_id"] == "16256042"
    assert room.get("inferred_from") == "execution_path"
