from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable, Sequence

from memory.applicability import (
    ApplicabilityJudge,
    ApplicabilityLabel,
    MockApplicabilityJudge,
    RuleBasedApplicabilityJudge,
)
from memory.long_term import MemoryCategory, MemoryDomain, MemoryFamily, TravelMemory
from repositories.long_term_memory import MemorySearchFilters, NoopLongTermMemoryRepository
from services.long_term_memory import MemoryService
from settings import Settings

USER_ID = "flow-test-user"
THREAD_ID = "flow-test-thread"


def make_recall_settings(**overrides) -> Settings:
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
    def __init__(self, memories: Sequence[TravelMemory]) -> None:
        self.memories = list(memories)
        self.last_filters: MemorySearchFilters | None = None
        self.last_domain_fetch: tuple[str, str, int] | None = None
        self.domain_fetch_count = 0

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
        self.domain_fetch_count += 1
        return [
            memory
            for memory in self.memories
            if memory.user_id == user_id
            and str(memory.domain) == domain
            and memory.family == MemoryFamily.TRAVEL_PREFERENCES
        ][:limit]


def _pref(
    *,
    memory_id: str,
    text: str,
    domain: MemoryDomain,
    category: MemoryCategory,
) -> TravelMemory:
    return TravelMemory(
        memory_id=memory_id,
        user_id=USER_ID,
        memory_text=text,
        category=category,
        domain=domain,
        evidence_text=text,
        source_thread_id=THREAD_ID,
    )


def profile_memory() -> TravelMemory:
    return TravelMemory(
        memory_id="profile-1",
        user_id=USER_ID,
        memory_text="anh Khoa",
        category=MemoryCategory.PROFILE_FACT,
        domain=MemoryDomain.GENERAL,
        evidence_text="Gọi tôi là anh Khoa",
        source_thread_id=THREAD_ID,
    )


def noise_memory_for(domain: str) -> TravelMemory:
    mapping = {
        "hotel": ("noise-hotel", "thích khách sạn gần biển", MemoryDomain.HOTEL, MemoryCategory.HOTEL_PREFERENCE),
        "flight": ("noise-flight", "ưu tiên bay sáng", MemoryDomain.FLIGHT, MemoryCategory.FLIGHT_PREFERENCE),
        "car": ("noise-car", "thích xe 7 chỗ", MemoryDomain.CAR, MemoryCategory.CAR_PREFERENCE),
        "excursion": ("noise-excursion", "thích tour biển", MemoryDomain.EXCURSION, MemoryCategory.EXCURSION_PREFERENCE),
    }
    memory_id, text, mem_domain, category = mapping[domain]
    return _pref(memory_id=memory_id, text=text, domain=mem_domain, category=category)


@dataclass(frozen=True)
class DomainFlowCase:
    domain: str
    agent_module: str
    tools_getter: str
    delegation_tool: str
    assistant_node: str
    user_query: str
    delegated_request: str
    expected_action: str
    memories: tuple[TravelMemory, ...]
    apply_ids: frozenset[str]
    exclude_ids: frozenset[str]
    apply_snippet: str
    exclude_snippet: str
    noise_domain: str
    judge: ApplicabilityJudge | None = None
    build_graph: Callable[..., Awaitable] | None = field(default=None, compare=False)


def _hotel_case() -> DomainFlowCase:
    apply_id, exclude_id = "hotel-apply", "hotel-exclude"
    return DomainFlowCase(
        domain="hotel",
        agent_module="agents.hotel.agent",
        tools_getter="get_hotel_tools",
        delegation_tool="ToHotelAssistant",
        assistant_node="hotel_assistant",
        user_query="Tìm khách sạn ở Hà Nội cho chuyến công tác",
        delegated_request="Tìm khách sạn Hà Nội cho chuyến công tác",
        expected_action="search_hotels",
        memories=(
            _pref(
                memory_id=apply_id,
                text="ngân sách 1-2 triệu",
                domain=MemoryDomain.HOTEL,
                category=MemoryCategory.HOTEL_PREFERENCE,
            ),
            _pref(
                memory_id=exclude_id,
                text="resort gần biển",
                domain=MemoryDomain.HOTEL,
                category=MemoryCategory.HOTEL_PREFERENCE,
            ),
            noise_memory_for("flight"),
        ),
        apply_ids=frozenset({apply_id}),
        exclude_ids=frozenset({exclude_id}),
        apply_snippet="ngân sách",
        exclude_snippet="biển",
        noise_domain="flight",
        judge=RuleBasedApplicabilityJudge(),
    )


def _flight_case() -> DomainFlowCase:
    apply_id, exclude_id = "flight-apply", "flight-exclude"
    return DomainFlowCase(
        domain="flight",
        agent_module="agents.flight.agent",
        tools_getter="get_flight_tools",
        delegation_tool="ToFlightAssistant",
        assistant_node="flight_assistant",
        user_query="Hôm nay tìm chuyến bay tối, sáng tôi bận",
        delegated_request="Tìm chuyến bay tối",
        expected_action="search_one_way",
        memories=(
            _pref(
                memory_id=exclude_id,
                text="ưu tiên bay sáng",
                domain=MemoryDomain.FLIGHT,
                category=MemoryCategory.FLIGHT_PREFERENCE,
            ),
            _pref(
                memory_id=apply_id,
                text="ưu tiên bay thẳng",
                domain=MemoryDomain.FLIGHT,
                category=MemoryCategory.FLIGHT_PREFERENCE,
            ),
            noise_memory_for("hotel"),
        ),
        apply_ids=frozenset({apply_id}),
        exclude_ids=frozenset({exclude_id}),
        apply_snippet="thẳng",
        exclude_snippet="sáng",
        noise_domain="hotel",
        judge=RuleBasedApplicabilityJudge(),
    )


def _car_case() -> DomainFlowCase:
    apply_id, exclude_id = "car-apply", "car-exclude"
    return DomainFlowCase(
        domain="car",
        agent_module="agents.car.agent",
        tools_getter="get_car_tools",
        delegation_tool="ToCarAssistant",
        assistant_node="car_assistant",
        user_query="Thuê xe số tự động ở Đà Nẵng",
        delegated_request="Thuê xe số tự động Đà Nẵng",
        expected_action="search_cars",
        memories=(
            _pref(
                memory_id=apply_id,
                text="thích xe số tự động",
                domain=MemoryDomain.CAR,
                category=MemoryCategory.CAR_PREFERENCE,
            ),
            _pref(
                memory_id=exclude_id,
                text="thích xe 7 chỗ",
                domain=MemoryDomain.CAR,
                category=MemoryCategory.CAR_PREFERENCE,
            ),
            noise_memory_for("excursion"),
        ),
        apply_ids=frozenset({apply_id}),
        exclude_ids=frozenset({exclude_id}),
        apply_snippet="tự động",
        exclude_snippet="7 chỗ",
        noise_domain="excursion",
        judge=MockApplicabilityJudge(
            overrides={
                apply_id: ApplicabilityLabel.APPLY,
                exclude_id: ApplicabilityLabel.IRRELEVANT,
            }
        ),
    )


def _excursion_case() -> DomainFlowCase:
    apply_id, exclude_id = "excursion-apply", "excursion-exclude"
    return DomainFlowCase(
        domain="excursion",
        agent_module="agents.excursion.agent",
        tools_getter="get_excursion_tools",
        delegation_tool="ToExcursionAssistant",
        assistant_node="excursion_assistant",
        user_query="Tìm tour tham quan ở Đà Nẵng",
        delegated_request="Tìm tour tham quan Đà Nẵng",
        expected_action="search_attractions",
        memories=(
            _pref(
                memory_id=apply_id,
                text="thích tour văn hóa",
                domain=MemoryDomain.EXCURSION,
                category=MemoryCategory.EXCURSION_PREFERENCE,
            ),
            _pref(
                memory_id=exclude_id,
                text="thích tour biển",
                domain=MemoryDomain.EXCURSION,
                category=MemoryCategory.EXCURSION_PREFERENCE,
            ),
            noise_memory_for("car"),
        ),
        apply_ids=frozenset({apply_id}),
        exclude_ids=frozenset({exclude_id}),
        apply_snippet="văn hóa",
        exclude_snippet="biển",
        noise_domain="car",
        judge=MockApplicabilityJudge(
            overrides={
                apply_id: ApplicabilityLabel.APPLY,
                exclude_id: ApplicabilityLabel.IRRELEVANT,
            }
        ),
    )


DOMAIN_FLOW_CASES: tuple[DomainFlowCase, ...] = (
    _hotel_case(),
    _flight_case(),
    _car_case(),
    _excursion_case(),
)


def make_recall_service(
    memories: Sequence[TravelMemory],
    *,
    judge: ApplicabilityJudge | None = None,
) -> tuple[MemoryService, FilteringRepo]:
    repo = FilteringRepo(memories)
    service = MemoryService(
        settings=make_recall_settings(),
        repository=repo,
        applicability_judge=judge or RuleBasedApplicabilityJudge(),
    )
    return service, repo


def all_parallel_memories() -> list[TravelMemory]:
    memories: list[TravelMemory] = [profile_memory()]
    for case in DOMAIN_FLOW_CASES:
        for memory in case.memories:
            if memory.family == MemoryFamily.TRAVEL_PREFERENCES:
                memories.append(memory)
    return memories
