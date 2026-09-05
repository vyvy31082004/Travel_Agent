import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from langchain_core.messages import AIMessage, HumanMessage

from agents.primary.agent import _branch_state
from agents.primary.domain_result import build_domain_branch_result
from agents.primary.state import merge_branch_results, merge_unique_ids
from memory.applicability import RuleBasedApplicabilityJudge
from memory.long_term import MemoryCategory, MemoryDomain, MemoryFamily, TravelMemory
from memory.recall_nodes import make_domain_memory_recall_node, make_global_recall_node
from repositories.long_term_memory import MemorySearchFilters, NoopLongTermMemoryRepository
from services.long_term_memory import MemoryService
from settings import Settings


def make_settings(**overrides):
    values = dict(
        database_url="postgresql://user:pass@localhost/db",
        cookie_secret="secret",
        long_term_memory_recall_enabled=True,
        long_term_memory_write_enabled=False,
        long_term_memory_recall_limit=5,
        long_term_memory_domain_candidate_limit=50,
        long_term_memory_applicability_judge_enabled=True,
        long_term_memory_action_inference_enabled=False,
    )
    values.update(overrides)
    return Settings(**values)


class FilteringRepo(NoopLongTermMemoryRepository):
    def __init__(self, memories):
        self.memories = memories
        self.last_filters: MemorySearchFilters | None = None
        self.last_domain_fetch: tuple[str, str, int] | None = None

    async def search_active_memories(self, filters: MemorySearchFilters):
        self.last_filters = filters
        results = self.memories
        if filters.domains:
            results = [
                memory
                for memory in results
                if str(memory.domain) in filters.domains
            ]
        if filters.families:
            results = [
                memory
                for memory in results
                if memory.family in filters.families
            ]
        return results

    async def fetch_active_domain_memories(self, *, user_id: str, domain: str, limit: int):
        self.last_domain_fetch = (user_id, domain, limit)
        return [
            memory
            for memory in self.memories
            if memory.user_id == user_id
            and str(memory.domain) == domain
            and memory.family == MemoryFamily.TRAVEL_PREFERENCES
        ][:limit]


def test_merge_reducers():
    assert merge_branch_results([], {"domain": "hotel"}) == [{"domain": "hotel"}]
    assert merge_branch_results([{"domain": "flight"}], [{"domain": "hotel"}]) == [
        {"domain": "flight"},
        {"domain": "hotel"},
    ]
    assert merge_unique_ids(["a"], ["b", "a"]) == ["a", "b"]


def test_branch_state_isolates_delegated_fields():
    state = {
        "messages": [
            HumanMessage(content="plan trip"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "hotel-1",
                        "name": "ToHotelAssistant",
                        "args": {
                            "request": "find hotel",
                            "turn_constraints": ["quiet area"],
                        },
                    },
                    {
                        "id": "flight-1",
                        "name": "ToFlightAssistant",
                        "args": {"request": "find flight", "turn_constraints": []},
                    },
                ],
            ),
        ]
    }
    hotel_branch = _branch_state(state, state["messages"][-1].tool_calls[0])
    flight_branch = _branch_state(state, state["messages"][-1].tool_calls[1])
    assert hotel_branch["delegated_request"] == "find hotel"
    assert flight_branch["delegated_request"] == "find flight"
    assert hotel_branch["turn_constraints"] == ["quiet area"]
    assert flight_branch["turn_constraints"] == []
    assert hotel_branch["user_query"] == "plan trip"


def test_recall_global_excludes_domain_travel_prefs():
    hotel = TravelMemory(
        memory_id="hotel-1",
        user_id="user-1",
        memory_text="ghét khách sạn sát biển",
        category=MemoryCategory.HOTEL_PREFERENCE,
        domain=MemoryDomain.HOTEL,
        evidence_text="ghét biển",
        source_thread_id="thread-1",
    )
    profile = TravelMemory(
        memory_id="profile-1",
        user_id="user-1",
        memory_text="anh Khoa",
        category=MemoryCategory.PROFILE_FACT,
        domain=MemoryDomain.GENERAL,
        evidence_text="Gọi tôi là anh Khoa",
        source_thread_id="thread-1",
    )
    general = TravelMemory(
        memory_id="general-1",
        user_id="user-1",
        memory_text="thích đi du lịch ngắn ngày",
        category=MemoryCategory.GENERAL_PREFERENCE,
        domain=MemoryDomain.GENERAL,
        evidence_text="thích đi du lịch ngắn ngày",
        source_thread_id="thread-1",
    )
    repo = FilteringRepo([hotel, profile, general])
    service = MemoryService(settings=make_settings(), repository=repo)
    result = asyncio.run(
        service.recall_global(user_id="user-1", query="lên kế hoạch Đà Nẵng")
    )
    assert "hotel-1" not in result.recalled_memory_ids
    assert "profile-1" in result.recalled_memory_ids
    assert "general-1" in result.recalled_memory_ids


def test_fetch_domain_candidates_uses_sql_pool():
    hotel = TravelMemory(
        memory_id="hotel-1",
        user_id="user-1",
        memory_text="ngân sách 1-2 triệu",
        category=MemoryCategory.HOTEL_PREFERENCE,
        domain=MemoryDomain.HOTEL,
        evidence_text="ngân sách 1-2 triệu",
        source_thread_id="thread-1",
    )
    flight = TravelMemory(
        memory_id="flight-1",
        user_id="user-1",
        memory_text="ưu tiên bay sáng",
        category=MemoryCategory.FLIGHT_PREFERENCE,
        domain=MemoryDomain.FLIGHT,
        evidence_text="bay sáng",
        source_thread_id="thread-1",
    )
    repo = FilteringRepo([hotel, flight])
    service = MemoryService(settings=make_settings(), repository=repo)
    candidates = asyncio.run(
        service.fetch_domain_candidates(user_id="user-1", domain=MemoryDomain.HOTEL.value)
    )
    assert [memory.memory_id for memory in candidates] == ["hotel-1"]
    assert repo.last_domain_fetch == ("user-1", "hotel", 50)


def test_recall_domain_with_applicability_filters_irrelevant_bathtub():
    """Bathtub has no search_hotels arg → IRRELEVANT and must leave recalled ids."""
    bathtub = TravelMemory(
        memory_id="hotel-1",
        user_id="user-1",
        memory_text="phòng có bồn tắm",
        category=MemoryCategory.HOTEL_PREFERENCE,
        domain=MemoryDomain.HOTEL,
        evidence_text="phòng có bồn tắm",
        source_thread_id="thread-1",
    )
    budget = TravelMemory(
        memory_id="hotel-2",
        user_id="user-1",
        memory_text="ngân sách 1-2 triệu",
        category=MemoryCategory.HOTEL_PREFERENCE,
        domain=MemoryDomain.HOTEL,
        evidence_text="ngân sách 1-2 triệu",
        source_thread_id="thread-1",
    )
    repo = FilteringRepo([bathtub, budget])
    service = MemoryService(
        settings=make_settings(),
        repository=repo,
        applicability_judge=RuleBasedApplicabilityJudge(),
    )
    result = asyncio.run(
        service.recall_domain_with_applicability(
            user_id="user-1",
            query="Tìm khách sạn ở Hà Nội cho chuyến công tác",
            domain=MemoryDomain.HOTEL.value,
            domain_state={},
        )
    )
    assert result.domain_action == "search_hotels"
    assert "hotel-2" in result.recalled_memory_ids
    assert "hotel-1" not in result.recalled_memory_ids
    assert "ngân sách" in result.memory_context


def test_domain_memory_recall_node_uses_user_query():
    hotel = TravelMemory(
        memory_id="hotel-1",
        user_id="user-1",
        memory_text="ngân sách 1-2 triệu",
        category=MemoryCategory.HOTEL_PREFERENCE,
        domain=MemoryDomain.HOTEL,
        evidence_text="ngân sách 1-2 triệu",
        source_thread_id="thread-1",
    )
    repo = FilteringRepo([hotel])
    service = MemoryService(
        settings=make_settings(),
        repository=repo,
        applicability_judge=RuleBasedApplicabilityJudge(),
    )
    node = make_domain_memory_recall_node(service, domain=MemoryDomain.HOTEL)
    result = asyncio.run(
        node(
            {
                "user_query": "Tìm khách sạn Đà Nẵng cho chuyến công tác",
                "delegated_request": "Tìm khách sạn Đà Nẵng cho chuyến công tác",
                "user_id": "user-1",
                "messages": [],
            },
            {"configurable": {"user_id": "user-1", "thread_id": "thread-1"}},
        )
    )
    assert "hotel-1" in result["recalled_memory_ids"]
    assert str(result["domain_action"]) == "search_hotels"
    assert "ngân sách" in result["domain_memory_context"]


def test_domain_memory_recall_prefers_full_utterance_over_delegated():
    large = TravelMemory(
        memory_id="m_large_group",
        user_id="user-1",
        memory_text="Ưu tiên tour nhóm lớn",
        category=MemoryCategory.EXCURSION_PREFERENCE,
        domain=MemoryDomain.EXCURSION,
        evidence_text="Ưu tiên tour nhóm lớn",
        source_thread_id="thread-1",
    )
    repo = FilteringRepo([large])
    service = MemoryService(
        settings=make_settings(),
        repository=repo,
        applicability_judge=RuleBasedApplicabilityJudge(),
    )
    node = make_domain_memory_recall_node(service, domain=MemoryDomain.EXCURSION)
    result = asyncio.run(
        node(
            {
                "trip_plan_user_message": (
                    "Từ giờ, khi chọn tour tôi ưu tiên nhóm nhỏ. "
                    "Tìm hoạt động ở Hội An cho 2 người vào chiều 12/10."
                ),
                "user_query": (
                    "Từ giờ, khi chọn tour tôi ưu tiên nhóm nhỏ. "
                    "Tìm hoạt động ở Hội An cho 2 người vào chiều 12/10."
                ),
                "delegated_request": (
                    "Tìm hoạt động/tour ở Hội An cho 2 người lớn vào chiều ngày 12/10/2026"
                ),
                "turn_constraints": ["ưu tiên nhóm nhỏ"],
                "user_id": "user-1",
                "messages": [],
            },
            {"configurable": {"user_id": "user-1", "thread_id": "thread-1"}},
        )
    )
    labels = {
        item["memory_id"]: item["label"] for item in result["memory_applicability"]
    }
    assert labels["m_large_group"] == "overridden"
    assert "m_large_group" not in result["recalled_memory_ids"]


def test_applicability_user_query_appends_missing_constraints():
    from memory.recall_nodes import applicability_user_query

    query = applicability_user_query(
        {
            "delegated_request": "Tìm hoạt động ở Hội An",
            "trip_plan_user_message": "",
            "user_query": "",
            "turn_constraints": ["ưu tiên nhóm nhỏ"],
        }
    )
    assert "Hội An" in query
    assert "nhóm nhỏ" in query


def test_build_domain_branch_result_merges_constraints():
    result = build_domain_branch_result(
        domain="hotel",
        summary="Found 3 hotels",
        turn_constraints=["ưu tiên yên tĩnh"],
        domain_memory_context="- ghét khách sạn sát biển",
        domain_action="search_hotels",
        visible_results={
            "req-1": {
                "domain": "hotel",
                "search_id": "s1",
                "displayed_item_ids": ["h1"],
                "labels": [],
            }
        },
    )
    assert result.domain == "hotel"
    assert result.summary == "Found 3 hotels"
    assert result.domain_action == "search_hotels"
    assert "ưu tiên yên tĩnh" in result.applied_constraints
    assert any("ghét" in item for item in result.applied_constraints)
    assert len(result.options) == 1


def test_global_recall_node():
    profile = TravelMemory(
        memory_id="profile-1",
        user_id="user-1",
        memory_text="anh Khoa",
        category=MemoryCategory.PROFILE_FACT,
        domain=MemoryDomain.GENERAL,
        evidence_text="Gọi tôi là anh Khoa",
        source_thread_id="thread-1",
    )
    repo = FilteringRepo([profile])
    service = MemoryService(settings=make_settings(), repository=repo)
    node = make_global_recall_node(service)
    result = asyncio.run(
        node(
            {"messages": [HumanMessage(content="hello")], "user_id": "user-1"},
            {"configurable": {"user_id": "user-1", "thread_id": "thread-1"}},
        )
    )
    assert "profile-1" in result["recalled_memory_ids"]
