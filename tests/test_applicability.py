import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memory.applicability import (
    ApplicabilityJudgment,
    ApplicabilityLabel,
    MockApplicabilityJudge,
    RuleBasedApplicabilityJudge,
    build_applicability_llm_prompt,
    partition_judgments,
    reconcile_judgments,
)
from memory.domain_actions import HotelAction, allowed_actions_for_domain
from memory.long_term import MemoryCategory, MemoryDomain, TravelMemory
from memory.task_router import infer_domain_action_heuristic


def _memory(
    memory_id: str,
    text: str,
    *,
    domain: MemoryDomain = MemoryDomain.HOTEL,
    category: MemoryCategory = MemoryCategory.HOTEL_PREFERENCE,
) -> TravelMemory:
    return TravelMemory(
        memory_id=memory_id,
        user_id="user-1",
        memory_text=text,
        category=category,
        domain=domain,
        evidence_text=text,
        source_thread_id="thread-1",
    )


def _hotel_memory(memory_id: str, text: str) -> TravelMemory:
    return _memory(memory_id, text)


def _run(coro):
    return asyncio.run(coro)


def test_allowed_actions_for_hotel():
    actions = allowed_actions_for_domain("hotel")
    assert HotelAction.SEARCH_HOTELS.value in actions


def test_infer_hotel_search_action():
    action = infer_domain_action_heuristic(
        user_query="Tìm khách sạn ở Hà Nội cho chuyến công tác",
        domain="hotel",
    )
    assert action == HotelAction.SEARCH_HOTELS.value


def test_infer_flight_search_action_from_multi_domain_request():
    action = infer_domain_action_heuristic(
        user_query=(
            "Lên kế hoạch Đà Nẵng: tìm khách sạn công tác, chuyến bay tối, "
            "thuê xe số tự động, tour tham quan"
        ),
        domain="flight",
    )
    assert action == "search_one_way"


def test_infer_actions_for_natural_vietnamese_phrasing():
    cases = [
        ("Tìm hotel công tác Hà Nội", "hotel", {}, "search_hotels"),
        (
            "Cho tôi xem các loại phòng của khách sạn này",
            "hotel",
            {},
            "get_hotel_details",
        ),
        ("Chọn giúp tôi phòng phù hợp nhất", "hotel", {}, "select_room"),
        ("Tìm vé SGN đi Hà Nội", "flight", {}, "search_one_way"),
        (
            "Chọn chuyến bay phù hợp nhất trong danh sách",
            "flight",
            {},
            "compare_offers",
        ),
    ]
    for query, domain, domain_state, expected in cases:
        assert infer_domain_action_heuristic(
            user_query=query,
            domain=domain,
            domain_state=domain_state,
        ) == expected


def test_hotel_business_beach_uncertain_bathtub_irrelevant():
    """Budget maps to price args; beach soft→uncertain; bathtub not a search arg→irrelevant."""
    memories = [
        _hotel_memory("budget", "ngân sách 1-2 triệu"),
        _hotel_memory("beach", "resort gần biển"),
        _hotel_memory("bathtub", "phòng có bồn tắm"),
    ]
    judge = RuleBasedApplicabilityJudge()
    judgments = _run(
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
    assert by_id["beach"] == ApplicabilityLabel.UNCERTAIN
    assert by_id["bathtub"] == ApplicabilityLabel.IRRELEVANT


def test_hotel_search_bathtub_always_irrelevant():
    judge = RuleBasedApplicabilityJudge()
    judgments = _run(
        judge.judge_batch(
            user_query="Tìm hotel nghỉ dưỡng cuối tuần",
            domain="hotel",
            domain_action="search_hotels",
            domain_state={},
            candidates=[_hotel_memory("bathtub", "thích bồn tắm")],
        )
    )
    assert judgments[0].label == ApplicabilityLabel.IRRELEVANT


def test_hotel_phu_quoc_quiet_and_beach_uncertain():
    """Quiet/beach have no search_hotels fields → uncertain; budget → apply."""
    memories = [
        _hotel_memory("m_budget", "Ngân sách hotel thường 1–2 triệu/đêm"),
        _hotel_memory("m_quiet", "Thích khách sạn yên tĩnh"),
        _hotel_memory("m_beach", "Thích khách sạn gần biển"),
    ]
    judge = RuleBasedApplicabilityJudge()
    judgments = _run(
        judge.judge_batch(
            user_query="Tìm khách sạn ở Phú Quốc cho tôi.",
            domain="hotel",
            domain_action="search_hotels",
            domain_state={},
            candidates=memories,
        )
    )
    by_id = {item.memory_id: item.label for item in judgments}
    assert by_id["m_budget"] == ApplicabilityLabel.APPLY
    assert by_id["m_quiet"] == ApplicabilityLabel.UNCERTAIN
    assert by_id["m_beach"] == ApplicabilityLabel.UNCERTAIN


def test_car_danang_capacity_applies_without_query_mention():
    """7 chỗ maps via user_needs on search_cars → apply even if query omits capacity."""
    memories = [
        _memory(
            "m_automatic",
            "Thích xe số tự động",
            domain=MemoryDomain.CAR,
            category=MemoryCategory.CAR_PREFERENCE,
        ),
        _memory(
            "m_seats",
            "Cần xe tối thiểu 7 chỗ",
            domain=MemoryDomain.CAR,
            category=MemoryCategory.CAR_PREFERENCE,
        ),
        _memory(
            "m_surcharge",
            "Tránh xe có phụ phí cao",
            domain=MemoryDomain.CAR,
            category=MemoryCategory.CAR_PREFERENCE,
        ),
    ]
    judge = RuleBasedApplicabilityJudge()
    judgments = _run(
        judge.judge_batch(
            user_query="Tôi cần xe ở Đà Nẵng từ 10 đến 13/10.",
            domain="car",
            domain_action="search_cars",
            domain_state={},
            candidates=memories,
        )
    )
    by_id = {item.memory_id: item.label for item in judgments}
    assert by_id["m_automatic"] == ApplicabilityLabel.APPLY
    assert by_id["m_seats"] == ApplicabilityLabel.APPLY
    assert by_id["m_surcharge"] == ApplicabilityLabel.UNCERTAIN


def test_override_hotel_lower_budget_keeps_quiet_uncertain():
    memories = [
        _hotel_memory("m_budget", "Ngân sách hotel thường 2–3 triệu/đêm"),
        _hotel_memory("m_quiet", "Thích khách sạn yên tĩnh"),
    ]
    judge = RuleBasedApplicabilityJudge()
    judgments = _run(
        judge.judge_batch(
            user_query="Lần này tìm khách sạn ở Đà Nẵng từ 10–12/10, dưới 1 triệu/đêm.",
            domain="hotel",
            domain_action="search_hotels",
            domain_state={},
            candidates=memories,
        )
    )
    by_id = {item.memory_id: item.label for item in judgments}
    assert by_id["m_budget"] == ApplicabilityLabel.OVERRIDDEN
    assert by_id["m_quiet"] == ApplicabilityLabel.UNCERTAIN


def test_override_car_manual_keeps_seats_apply():
    memories = [
        _memory(
            "m_automatic",
            "Thích xe số tự động",
            domain=MemoryDomain.CAR,
            category=MemoryCategory.CAR_PREFERENCE,
        ),
        _memory(
            "m_seats",
            "Cần xe tối thiểu 7 chỗ",
            domain=MemoryDomain.CAR,
            category=MemoryCategory.CAR_PREFERENCE,
        ),
    ]
    judge = RuleBasedApplicabilityJudge()
    judgments = _run(
        judge.judge_batch(
            user_query="Lần này tìm xe số sàn ở Đà Nẵng từ 10–12/10.",
            domain="car",
            domain_action="search_cars",
            domain_state={},
            candidates=memories,
        )
    )
    by_id = {item.memory_id: item.label for item in judgments}
    assert by_id["m_automatic"] == ApplicabilityLabel.OVERRIDDEN
    assert by_id["m_seats"] == ApplicabilityLabel.APPLY


def test_flight_evening_overrides_morning():
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
    judgments = _run(
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


def test_flight_han_origin_overrides_sgn_memory():
    memory = TravelMemory(
        memory_id="origin",
        user_id="user-1",
        memory_text="thường bay từ SGN",
        category=MemoryCategory.FLIGHT_PREFERENCE,
        domain=MemoryDomain.FLIGHT,
        evidence_text="thường bay từ SGN",
        source_thread_id="thread-1",
    )
    judge = RuleBasedApplicabilityJudge()
    judgments = _run(
        judge.judge_batch(
            user_query="Tôi đang ở Hà Nội, bay từ HAN đi Đà Nẵng",
            domain="flight",
            domain_action="search_one_way",
            domain_state={},
            candidates=[memory],
        )
    )
    assert judgments[0].label == ApplicabilityLabel.OVERRIDDEN


def test_flight_monday_hn_tool_mapped_prefs_apply():
    memories = [
        _memory(
            "m_economy",
            "Thường bay hạng phổ thông (economy) khi đi du lịch",
            domain=MemoryDomain.FLIGHT,
            category=MemoryCategory.FLIGHT_PREFERENCE,
        ),
        _memory(
            "m_direct",
            "Ưu tiên bay thẳng, tránh nối chuyến",
            domain=MemoryDomain.FLIGHT,
            category=MemoryCategory.FLIGHT_PREFERENCE,
        ),
        _memory(
            "m_departure",
            "Thường bay từ TP.HCM (SGN)",
            domain=MemoryDomain.FLIGHT,
            category=MemoryCategory.FLIGHT_PREFERENCE,
        ),
    ]
    judge = RuleBasedApplicabilityJudge()
    judgments = _run(
        judge.judge_batch(
            user_query="Bay ra Hà Nội sáng thứ Hai nhé.",
            domain="flight",
            domain_action="search_one_way",
            domain_state={},
            candidates=memories,
        )
    )
    by_id = {item.memory_id: item.label for item in judgments}
    assert by_id["m_economy"] == ApplicabilityLabel.APPLY
    assert by_id["m_direct"] == ApplicabilityLabel.APPLY
    assert by_id["m_departure"] == ApplicabilityLabel.APPLY


def test_excursion_danang_nature_apply_crowd_uncertain():
    memories = [
        _memory(
            "m_nature",
            "Thích điểm tham quan thiên nhiên",
            domain=MemoryDomain.EXCURSION,
            category=MemoryCategory.EXCURSION_PREFERENCE,
        ),
        _memory(
            "m_crowded",
            "Tránh điểm quá đông đúc",
            domain=MemoryDomain.EXCURSION,
            category=MemoryCategory.EXCURSION_PREFERENCE,
        ),
    ]
    judge = RuleBasedApplicabilityJudge()
    judgments = _run(
        judge.judge_batch(
            user_query="Mai ở Đà Nẵng nên đi đâu?",
            domain="excursion",
            domain_action="search_attractions",
            domain_state={},
            candidates=memories,
        )
    )
    by_id = {item.memory_id: item.label for item in judgments}
    assert by_id["m_nature"] == ApplicabilityLabel.APPLY
    assert by_id["m_crowded"] == ApplicabilityLabel.UNCERTAIN


def test_override_flight_business_class():
    memories = [
        _memory(
            "m_economy",
            "Thường bay hạng phổ thông (economy) khi đi du lịch",
            domain=MemoryDomain.FLIGHT,
            category=MemoryCategory.FLIGHT_PREFERENCE,
        ),
        _memory(
            "m_direct",
            "Ưu tiên bay thẳng, tránh nối chuyến",
            domain=MemoryDomain.FLIGHT,
            category=MemoryCategory.FLIGHT_PREFERENCE,
        ),
    ]
    judge = RuleBasedApplicabilityJudge()
    judgments = _run(
        judge.judge_batch(
            user_query="Chuyến này tìm chuyến TP.HCM–Hà Nội ngày 10/10, bay business class.",
            domain="flight",
            domain_action="search_one_way",
            domain_state={},
            candidates=memories,
        )
    )
    by_id = {item.memory_id: item.label for item in judgments}
    assert by_id["m_economy"] == ApplicabilityLabel.OVERRIDDEN
    assert by_id["m_direct"] == ApplicabilityLabel.APPLY


def test_override_excursion_higher_budget():
    memories = [
        _memory(
            "m_budget",
            "Ngân sách tour thường dưới 300 nghìn/người",
            domain=MemoryDomain.EXCURSION,
            category=MemoryCategory.EXCURSION_PREFERENCE,
        ),
        _memory(
            "m_nature",
            "Thích điểm tham quan thiên nhiên",
            domain=MemoryDomain.EXCURSION,
            category=MemoryCategory.EXCURSION_PREFERENCE,
        ),
    ]
    judge = RuleBasedApplicabilityJudge()
    judgments = _run(
        judge.judge_batch(
            user_query="Lần này tìm hoạt động ở Đà Nẵng ngày 10/10, ngân sách tối đa 700 nghìn/người.",
            domain="excursion",
            domain_action="search_attractions",
            domain_state={},
            candidates=memories,
        )
    )
    by_id = {item.memory_id: item.label for item in judgments}
    assert by_id["m_budget"] == ApplicabilityLabel.OVERRIDDEN
    assert by_id["m_nature"] == ApplicabilityLabel.APPLY


def test_override_excursion_group_size():
    memories = [
        _memory(
            "m_large_group",
            "Ưu tiên tour nhóm lớn",
            domain=MemoryDomain.EXCURSION,
            category=MemoryCategory.EXCURSION_PREFERENCE,
        ),
        _memory(
            "m_nature",
            "Thích điểm tham quan thiên nhiên",
            domain=MemoryDomain.EXCURSION,
            category=MemoryCategory.EXCURSION_PREFERENCE,
        ),
    ]
    judge = RuleBasedApplicabilityJudge()
    judgments = _run(
        judge.judge_batch(
            user_query=(
                "Từ giờ, khi chọn tour tôi ưu tiên nhóm nhỏ. "
                "Tìm hoạt động ở Hội An cho 2 người vào chiều 12/10."
            ),
            domain="excursion",
            domain_action="search_attractions",
            domain_state={},
            candidates=memories,
        )
    )
    by_id = {item.memory_id: item.label for item in judgments}
    assert by_id["m_large_group"] == ApplicabilityLabel.OVERRIDDEN
    assert by_id["m_nature"] == ApplicabilityLabel.APPLY


def test_override_excursion_group_size_via_turn_constraints():
    memories = [
        _memory(
            "m_large_group",
            "Ưu tiên tour nhóm lớn",
            domain=MemoryDomain.EXCURSION,
            category=MemoryCategory.EXCURSION_PREFERENCE,
        )
    ]
    judge = RuleBasedApplicabilityJudge()
    judgments = _run(
        judge.judge_batch(
            user_query="Tìm hoạt động/tour ở Hội An cho 2 người lớn vào chiều ngày 12/10/2026",
            domain="excursion",
            domain_action="search_attractions",
            domain_state={"turn_constraints": ["ưu tiên nhóm nhỏ"]},
            candidates=memories,
        )
    )
    assert judgments[0].label == ApplicabilityLabel.OVERRIDDEN


def test_partition_judgments_apply_and_uncertain():
    memories = [
        _hotel_memory("a", "quiet"),
        _hotel_memory("b", "budget"),
    ]
    judgments = _run(
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


def test_reconcile_upgrades_uncertain_budget_to_apply():
    memories = [_hotel_memory("m_budget", "Ngân sách hotel thường 1–2 triệu/đêm")]
    llm_judgments = [
        ApplicabilityJudgment(
            memory_id="m_budget",
            label=ApplicabilityLabel.UNCERTAIN,
            confidence=0.6,
            reason="query omits budget",
        )
    ]
    reconciled = _run(
        reconcile_judgments(
            memories,
            llm_judgments,
            user_query="Tìm khách sạn ở Phú Quốc",
            domain="hotel",
            domain_action="search_hotels",
            domain_state={},
        )
    )
    assert reconciled[0].label == ApplicabilityLabel.APPLY


def test_reconcile_keeps_overridden():
    memories = [
        _memory(
            "morning",
            "ưu tiên bay sáng",
            domain=MemoryDomain.FLIGHT,
            category=MemoryCategory.FLIGHT_PREFERENCE,
        )
    ]
    llm_judgments = [
        ApplicabilityJudgment(
            memory_id="morning",
            label=ApplicabilityLabel.OVERRIDDEN,
            confidence=0.9,
            reason="user wants evening",
        )
    ]
    reconciled = _run(
        reconcile_judgments(
            memories,
            llm_judgments,
            user_query="Hôm nay tìm chuyến bay tối",
            domain="flight",
            domain_action="search_one_way",
            domain_state={},
        )
    )
    assert reconciled[0].label == ApplicabilityLabel.OVERRIDDEN


def test_reconcile_upgrades_group_size_override():
    memories = [
        _memory(
            "m_large_group",
            "Ưu tiên tour nhóm lớn",
            domain=MemoryDomain.EXCURSION,
            category=MemoryCategory.EXCURSION_PREFERENCE,
        )
    ]
    llm_judgments = [
        ApplicabilityJudgment(
            memory_id="m_large_group",
            label=ApplicabilityLabel.APPLY,
            confidence=0.8,
            reason="relevant filter for excursion search",
        )
    ]
    reconciled = _run(
        reconcile_judgments(
            memories,
            llm_judgments,
            user_query="Tìm hoạt động/tour ở Hội An cho 2 người lớn vào chiều ngày 12/10/2026",
            domain="excursion",
            domain_action="search_attractions",
            domain_state={"turn_constraints": ["ưu tiên nhóm nhỏ"]},
        )
    )
    assert reconciled[0].label == ApplicabilityLabel.OVERRIDDEN


def test_llm_prompt_encodes_tool_field_rubric():
    prompt = build_applicability_llm_prompt(
        user_query="Tìm khách sạn ở Phú Quốc",
        domain="hotel",
        domain_action="search_hotels",
        domain_state={},
        payload=[{"memory_id": "m1", "memory_text": "Thích yên tĩnh", "condition": None}],
    )
    assert "no quiet tool field" in prompt
    assert "tối thiểu 7 chỗ" in prompt and "user_needs" in prompt
    assert "apply as a ranking constraint" not in prompt
    assert "7-seat applies only when the current" not in prompt
