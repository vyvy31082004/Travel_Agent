import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memory.applicability import (
    ApplicabilityLabel,
    MockApplicabilityJudge,
    RuleBasedApplicabilityJudge,
    partition_judgments,
)
from memory.domain_actions import HotelAction, allowed_actions_for_domain
from memory.long_term import MemoryCategory, MemoryDomain, TravelMemory
from memory.task_router import infer_domain_action_heuristic


def _hotel_memory(memory_id: str, text: str) -> TravelMemory:
    return TravelMemory(
        memory_id=memory_id,
        user_id="user-1",
        memory_text=text,
        category=MemoryCategory.HOTEL_PREFERENCE,
        domain=MemoryDomain.HOTEL,
        evidence_text=text,
        source_thread_id="thread-1",
    )


def test_allowed_actions_for_hotel():
    actions = allowed_actions_for_domain("hotel")
    assert HotelAction.SEARCH_HOTELS.value in actions


def test_infer_hotel_search_action():
    action = infer_domain_action_heuristic(
        user_query="Tìm khách sạn ở Hà Nội cho chuyến công tác",
        domain="hotel",
    )
    assert action == HotelAction.SEARCH_HOTELS.value


def test_rule_based_hotel_business_irrelevant_beach():
    memories = [
        _hotel_memory("budget", "ngân sách 1-2 triệu"),
        _hotel_memory("beach", "resort gần biển"),
        _hotel_memory("bathtub", "phòng có bồn tắm"),
    ]
    judge = RuleBasedApplicabilityJudge()
    judgments = asyncio.run(
        judge.judge_batch(
            user_query="Tìm khách sạn ở Hà Nội cho chuyến công tác",
            domain="hotel",
            domain_action="search_hotels",
            domain_state={},
            candidates=memories,
        )
    )
    by_id = {item.memory_id: item.label for item in judgments}
    assert by_id["budget"] == ApplicabilityLabel.APPLY
    assert by_id["beach"] == ApplicabilityLabel.IRRELEVANT
    assert by_id["bathtub"] == ApplicabilityLabel.IRRELEVANT


def test_rule_based_flight_evening_overrides_morning():
    memories = [
        TravelMemory(
            memory_id="morning",
            user_id="user-1",
            memory_text="ưu tiên bay sáng",
            category=MemoryCategory.FLIGHT_PREFERENCE,
            domain=MemoryDomain.FLIGHT,
            evidence_text="ưu tiên bay sáng",
            source_thread_id="thread-1",
        ),
        TravelMemory(
            memory_id="direct",
            user_id="user-1",
            memory_text="ưu tiên bay thẳng",
            category=MemoryCategory.FLIGHT_PREFERENCE,
            domain=MemoryDomain.FLIGHT,
            evidence_text="ưu tiên bay thẳng",
            source_thread_id="thread-1",
        ),
    ]
    judge = RuleBasedApplicabilityJudge()
    judgments = asyncio.run(
        judge.judge_batch(
            user_query="Hôm nay tìm chuyến bay tối, sáng tôi bận",
            domain="flight",
            domain_action="search_one_way",
            domain_state={},
            candidates=memories,
        )
    )
    by_id = {item.memory_id: item.label for item in judgments}
    assert by_id["morning"] == ApplicabilityLabel.OVERRIDDEN
    assert by_id["direct"] == ApplicabilityLabel.APPLY


def test_partition_judgments_apply_and_uncertain():
    memories = [
        _hotel_memory("a", "quiet"),
        _hotel_memory("b", "budget"),
    ]
    judgments = asyncio.run(
        MockApplicabilityJudge(
            overrides={"a": ApplicabilityLabel.APPLY, "b": ApplicabilityLabel.UNCERTAIN}
        ).judge_batch(
            user_query="q",
            domain="hotel",
            domain_action="search_hotels",
            domain_state={},
            candidates=memories,
        )
    )
    apply_memories, uncertain_memories, _ = partition_judgments(memories, judgments)
    assert [memory.memory_id for memory in apply_memories] == ["a"]
    assert [memory.memory_id for memory in uncertain_memories] == ["b"]
