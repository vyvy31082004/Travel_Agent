from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from e2e_eval.trace_collector import TraceCollector


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
