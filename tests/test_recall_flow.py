from __future__ import annotations

import asyncio
import contextlib
from contextlib import contextmanager
import importlib
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "tests"))

from memory.applicability import ApplicabilityLabel, MockApplicabilityJudge
from memory.long_term import MemoryFamily

from helpers.recall_flow import (
    DOMAIN_FLOW_CASES,
    THREAD_ID,
    USER_ID,
    DomainFlowCase,
    all_parallel_memories,
    make_recall_service,
    profile_memory,
)

GRAPH_BUILDERS = {
    "hotel": "agents.hotel.agent.build_hotel_graph",
    "flight": "agents.flight.agent.build_flight_graph",
    "car": "agents.car.agent.build_car_graph",
    "excursion": "agents.excursion.agent.build_excursion_graph",
}


def _import_builder(domain: str):
    module_path, func_name = GRAPH_BUILDERS[domain].rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, func_name)


@contextmanager
def patch_domain_tools(case: DomainFlowCase):
    with patch(
        f"{case.agent_module}.{case.tools_getter}",
        AsyncMock(return_value=[]),
    ):
        yield


@contextmanager
def patch_all_domain_tools():
    with contextlib_exit_stack_tools():
        yield


def contextlib_exit_stack_tools():
    from contextlib import ExitStack

    stack = ExitStack()
    for case in DOMAIN_FLOW_CASES:
        stack.enter_context(
            patch(
                f"{case.agent_module}.{case.tools_getter}",
                AsyncMock(return_value=[]),
            )
        )
    return stack


def _subagent_input(case: DomainFlowCase) -> dict:
    return {
        "user_id": USER_ID,
        "thread_id": THREAD_ID,
        "user_query": case.user_query,
        "messages": [HumanMessage(content=case.user_query)],
    }


def _config() -> dict:
    return {"configurable": {"user_id": USER_ID, "thread_id": THREAD_ID}}


def _assert_subagent_recall_result(
    case: DomainFlowCase,
    *,
    captured: dict,
    repo,
    result: dict,
) -> None:
    assert repo.last_domain_fetch == (USER_ID, case.domain, 50)
    assert str(captured.get("domain_action") or "") == case.expected_action
    context = (captured.get("domain_memory_context") or "").lower()
    soft = (captured.get("domain_soft_memory_context") or "").lower()
    combined = f"{context}\n{soft}"
    assert case.apply_snippet.lower() in combined
    assert case.exclude_snippet.lower() not in combined
    assert "memory_context" not in captured
    noise = next(m for m in case.memories if str(m.domain) == case.noise_domain)
    assert (noise.memory_text or "").lower() not in combined
    recalled = set(
        captured.get("recalled_memory_ids") or result.get("recalled_memory_ids") or []
    )
    assert case.apply_ids <= recalled
    assert recalled.isdisjoint(case.exclude_ids)


@pytest.mark.parametrize("case", DOMAIN_FLOW_CASES, ids=lambda c: c.domain)
def test_subagent_recall_flow_before_chat(case: DomainFlowCase):
    async def _run():
        captured: dict = {}

        async def fake_chat(**kwargs):
            captured.update(kwargs["state"])
            return {"messages": []}

        service, repo = make_recall_service(case.memories, judge=case.judge)
        build_graph = _import_builder(case.domain)

        with patch_domain_tools(case):
            with patch(
                f"{case.agent_module}.domain_chat_with_memory",
                fake_chat,
            ):
                graph = await build_graph(memory_service=service, repo=None)
                result = await graph.ainvoke(_subagent_input(case), _config())

        _assert_subagent_recall_result(case, captured=captured, repo=repo, result=result)

    asyncio.run(_run())


@pytest.mark.parametrize("case", DOMAIN_FLOW_CASES, ids=lambda c: c.domain)
def test_primary_delegation_recall_flow(case: DomainFlowCase):
    async def _run():
        from agents.primary.agent import build_primary_graph

        calls = {"n": 0}
        memories = [profile_memory(), *case.memories]
        service, repo = make_recall_service(memories, judge=case.judge)

        async def fake_primary_chat(state, config):
            calls["n"] += 1
            if calls["n"] == 1:
                return {
                    "messages": [
                        AIMessage(
                            content="",
                            tool_calls=[
                                {
                                    "id": f"{case.domain}-tc",
                                    "name": case.delegation_tool,
                                    "args": {
                                        "request": case.delegated_request,
                                        "turn_constraints": [],
                                    },
                                }
                            ],
                        )
                    ]
                }
            return {"messages": [AIMessage(content="synthesis complete")]}

        captured: dict = {}

        async def fake_chat(**kwargs):
            captured.update(kwargs["state"])
            return {
                "messages": [AIMessage(content=f"{case.domain} branch done")],
                "domain_action": kwargs["state"].get("domain_action"),
                "domain_memory_context": kwargs["state"].get("domain_memory_context"),
                "domain_soft_memory_context": kwargs["state"].get(
                    "domain_soft_memory_context"
                ),
                "recalled_memory_ids": kwargs["state"].get("recalled_memory_ids") or [],
            }

        with contextlib_exit_stack_tools():
            with patch("agents.primary.agent.primary_chat", fake_primary_chat):
                with patch(
                    f"{case.agent_module}.domain_chat_with_memory",
                    fake_chat,
                ):
                    graph = await build_primary_graph(
                        checkpointer=MemorySaver(),
                        repo=None,
                        memory_service=service,
                    )
                    result = await graph.ainvoke(
                        {
                            "messages": [HumanMessage(content=case.user_query)],
                            "user_id": USER_ID,
                            "thread_id": THREAD_ID,
                            "trip_plan_user_message": case.user_query,
                        },
                        _config(),
                    )

        assert "anh Khoa" in (result.get("memory_context") or "")
        for memory in case.memories:
            if (
                memory.family == MemoryFamily.TRAVEL_PREFERENCES
                and str(memory.domain) == case.domain
            ):
                assert (memory.memory_text or "") not in (result.get("memory_context") or "")

        branches = result.get("domain_branch_results") or []
        assert len(branches) == 1
        branch = branches[0]
        assert branch["domain"] == case.domain
        assert str(branch.get("domain_action") or "") == case.expected_action

        recalled = set(result.get("recalled_memory_ids") or [])
        assert case.apply_ids <= recalled
        assert recalled.isdisjoint(case.exclude_ids)

        _assert_subagent_recall_result(
            case,
            captured=captured,
            repo=repo,
            result={"recalled_memory_ids": list(recalled)},
        )

    asyncio.run(_run())


def _parallel_judge() -> MockApplicabilityJudge:
    overrides: dict[str, ApplicabilityLabel] = {}
    for case in DOMAIN_FLOW_CASES:
        for memory_id in case.apply_ids:
            overrides[memory_id] = ApplicabilityLabel.APPLY
        label = (
            ApplicabilityLabel.OVERRIDDEN
            if case.domain == "flight"
            else ApplicabilityLabel.IRRELEVANT
        )
        for memory_id in case.exclude_ids:
            overrides[memory_id] = label
    return MockApplicabilityJudge(overrides=overrides)


def test_primary_parallel_four_domain_recall_flow():
    async def _run():
        from agents.primary.agent import build_primary_graph

        calls = {"n": 0}
        service, repo = make_recall_service(
            all_parallel_memories(),
            judge=_parallel_judge(),
        )

        async def fake_primary_chat(state, config):
            calls["n"] += 1
            if calls["n"] == 1:
                tool_calls = []
                for index, case in enumerate(DOMAIN_FLOW_CASES):
                    tool_calls.append(
                        {
                            "id": f"{case.domain}-tc-{index}",
                            "name": case.delegation_tool,
                            "args": {
                                "request": case.delegated_request,
                                "turn_constraints": [],
                            },
                        }
                    )
                return {"messages": [AIMessage(content="", tool_calls=tool_calls)]}
            return {"messages": [AIMessage(content="trip plan synthesis")]}

        captured_by_domain: dict[str, dict] = {}

        def make_fake_chat(domain: str):
            async def fake_chat(**kwargs):
                captured_by_domain[domain] = dict(kwargs["state"])
                return {
                    "messages": [AIMessage(content=f"{domain} ok")],
                    "domain_action": kwargs["state"].get("domain_action"),
                    "domain_memory_context": kwargs["state"].get("domain_memory_context"),
                    "domain_soft_memory_context": kwargs["state"].get(
                        "domain_soft_memory_context"
                    ),
                    "recalled_memory_ids": kwargs["state"].get("recalled_memory_ids") or [],
                }

            return fake_chat

        patches = [
            patch(
                f"{case.agent_module}.domain_chat_with_memory",
                make_fake_chat(case.domain),
            )
            for case in DOMAIN_FLOW_CASES
        ]

        full_trip_message = (
            "Lên kế hoạch Đà Nẵng: tìm khách sạn công tác, chuyến bay tối, "
            "thuê xe số tự động, tour tham quan"
        )

        with contextlib_exit_stack_tools():
            with patch("agents.primary.agent.primary_chat", fake_primary_chat):
                with contextlib.ExitStack() as stack:
                    for item in patches:
                        stack.enter_context(item)
                    graph = await build_primary_graph(
                        checkpointer=MemorySaver(),
                        repo=None,
                        memory_service=service,
                    )
                    result = await graph.ainvoke(
                        {
                            "messages": [HumanMessage(content=full_trip_message)],
                            "user_id": USER_ID,
                            "thread_id": THREAD_ID,
                            "trip_plan_user_message": full_trip_message,
                        },
                        _config(),
                    )

        branches = result.get("domain_branch_results") or []
        assert len(branches) == 4
        branch_domains = {branch["domain"] for branch in branches}
        assert branch_domains == {"hotel", "flight", "car", "excursion"}

        recalled = set(result.get("recalled_memory_ids") or [])
        all_apply: set[str] = set()
        all_exclude: set[str] = set()
        for case in DOMAIN_FLOW_CASES:
            all_apply |= set(case.apply_ids)
            all_exclude |= set(case.exclude_ids)
            captured = captured_by_domain.get(case.domain, {})
            assert str(captured.get("domain_action") or "") == case.expected_action
            assert case.apply_snippet.lower() in (
                (captured.get("domain_memory_context") or "")
                + (captured.get("domain_soft_memory_context") or "")
            ).lower()
            assert "memory_context" not in captured
            noise = next(m for m in case.memories if str(m.domain) == case.noise_domain)
            noise_text = (noise.memory_text or "").lower()
            combined = (
                (captured.get("domain_memory_context") or "")
                + (captured.get("domain_soft_memory_context") or "")
            ).lower()
            assert noise_text not in combined

        assert all_apply <= recalled
        assert recalled.isdisjoint(all_exclude)
        assert repo.domain_fetch_count == 4

    asyncio.run(_run())
