import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memory.applicability import (
    ApplicabilityJudgment,
    ApplicabilityLabel,
    LlmApplicabilityJudge,
    MockApplicabilityJudge,
    RuleBasedApplicabilityJudge,
    build_applicability_llm_prompt,
    partition_judgments,
    reconcile_judgments,
)
from memory.domain_actions import HotelAction, allowed_actions_for_domain
from memory.long_term import MemoryCategory, MemoryDomain, TravelMemory
from memory.task_router import infer_domain_action_heuristic
from memory_eval.store import InMemoryLongTermMemoryRepository
from services.long_term_memory import MemoryService
from settings import Settings


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


def test_car_danang_capacity_uncertain_without_seats_tool_arg():
    """Seat capacity is soft on search_cars — no dedicated seats tool arg."""
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
    assert by_id["m_seats"] == ApplicabilityLabel.UNCERTAIN
    assert by_id["m_surcharge"] == ApplicabilityLabel.UNCERTAIN


def test_car_five_seat_capacity_uncertain_on_search():
    """N-chỗ prefs stay uncertain on search_cars (no seats tool arg)."""
    memories = [
        _memory(
            "m_seats",
            "Cần xe 5 chỗ",
            domain=MemoryDomain.CAR,
            category=MemoryCategory.CAR_PREFERENCE,
        ),
        _memory(
            "m_four",
            "Thường thuê xe 4 chỗ",
            domain=MemoryDomain.CAR,
            category=MemoryCategory.CAR_PREFERENCE,
        ),
    ]
    judge = RuleBasedApplicabilityJudge()
    judgments = _run(
        judge.judge_batch(
            user_query="Tìm xe luôn, tôi đi 4 người.",
            domain="car",
            domain_action="search_cars",
            domain_state={},
            candidates=memories,
        )
    )
    by_id = {item.memory_id: item.label for item in judgments}
    assert by_id["m_seats"] == ApplicabilityLabel.UNCERTAIN
    assert by_id["m_four"] == ApplicabilityLabel.UNCERTAIN


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


def test_override_car_manual_keeps_seats_uncertain():
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
    assert by_id["m_seats"] == ApplicabilityLabel.UNCERTAIN


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


def test_excursion_danang_nature_uncertain_crowd_uncertain():
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
    assert by_id["m_nature"] == ApplicabilityLabel.UNCERTAIN
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
    assert by_id["m_nature"] == ApplicabilityLabel.UNCERTAIN


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
    assert by_id["m_nature"] == ApplicabilityLabel.UNCERTAIN


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


def test_reconcile_uncertain_fence_against_llm_overridden():
    """Matched rule uncertain (e.g. cheapest vs schedule) must not be dropped by LLM overridden."""
    memories = [
        _memory(
            "cheap",
            "thường chọn rẻ nhất",
            domain=MemoryDomain.FLIGHT,
            category=MemoryCategory.FLIGHT_PREFERENCE,
        )
    ]
    llm_judgments = [
        ApplicabilityJudgment(
            memory_id="cheap",
            label=ApplicabilityLabel.OVERRIDDEN,
            confidence=0.95,
            reason="user prioritized schedule",
        )
    ]
    reconciled = _run(
        reconcile_judgments(
            memories,
            llm_judgments,
            user_query="Tìm chuyến bay đúng giờ nhất",
            domain="flight",
            domain_action="search_one_way",
            domain_state={},
        )
    )
    # Rule for 'rẻ nhất' + 'đúng giờ' is uncertain matched.
    assert reconciled[0].label == ApplicabilityLabel.UNCERTAIN


def test_reconcile_llm_overridden_wins_over_matched_apply():
    """True user contradiction (LLM overridden) wins over hard tool-field rule."""
    memories = [
        _memory(
            "direct",
            "ưu tiên bay thẳng",
            domain=MemoryDomain.FLIGHT,
            category=MemoryCategory.FLIGHT_PREFERENCE,
        )
    ]
    llm_judgments = [
        ApplicabilityJudgment(
            memory_id="direct",
            label=ApplicabilityLabel.OVERRIDDEN,
            confidence=0.95,
            reason="user explicitly said 'thay vì bay thẳng, lần này tôi chấp nhận nối chuyến'",
        )
    ]
    reconciled = _run(
        reconcile_judgments(
            memories,
            llm_judgments,
            user_query="Thay vì bay thẳng, lần này tôi chấp nhận nối chuyến để tiết kiệm",
            domain="flight",
            domain_action="search_one_way",
            domain_state={},
        )
    )
    # Rule for 'bay thẳng' is APPLY matched (usually).
    # LLM overridden (high conf) wins over APPLY to allow user cancellation.
    assert reconciled[0].label == ApplicabilityLabel.OVERRIDDEN


def test_reconcile_keeps_rule_uncertain_when_llm_irrelevant_hotel_details():
    memories = [
        _hotel_memory("bathtub", "ưu tiên phòng có bồn tắm"),
        _hotel_memory("budget", "ngân sách 1-2 triệu"),
    ]
    llm_judgments = [
        ApplicabilityJudgment(
            memory_id="bathtub",
            label=ApplicabilityLabel.IRRELEVANT,
            confidence=0.95,
            reason="copied search_hotels bathtub pattern",
        ),
        ApplicabilityJudgment(
            memory_id="budget",
            label=ApplicabilityLabel.IRRELEVANT,
            confidence=0.95,
            reason="no price filter on details tools",
        ),
    ]
    reconciled = _run(
        reconcile_judgments(
            memories,
            llm_judgments,
            user_query="Cho tôi xem các loại phòng của khách sạn này",
            domain="hotel",
            domain_action="get_hotel_details",
            domain_state={"selected_hotel_id": "hotel_123"},
        )
    )
    by_id = {item.memory_id: item.label for item in reconciled}
    assert by_id["bathtub"] == ApplicabilityLabel.UNCERTAIN
    assert by_id["budget"] == ApplicabilityLabel.UNCERTAIN


def test_reconcile_keeps_rule_irrelevant_bathtub_on_search():
    memories = [_hotel_memory("bathtub", "phòng có bồn tắm")]
    llm_judgments = [
        ApplicabilityJudgment(
            memory_id="bathtub",
            label=ApplicabilityLabel.APPLY,
            confidence=0.9,
            reason="soft-rank amenity",
        )
    ]
    reconciled = _run(
        reconcile_judgments(
            memories,
            llm_judgments,
            user_query="Tìm khách sạn ở Hà Nội",
            domain="hotel",
            domain_action="search_hotels",
            domain_state={},
        )
    )
    assert reconciled[0].label == ApplicabilityLabel.IRRELEVANT


def test_reconcile_demotes_llm_apply_when_rule_unmatched():
    memories = [
        _memory(
            "obscure",
            "thích phòng có view núi tuyết",
            domain=MemoryDomain.HOTEL,
            category=MemoryCategory.HOTEL_PREFERENCE,
        )
    ]
    llm_judgments = [
        ApplicabilityJudgment(
            memory_id="obscure",
            label=ApplicabilityLabel.APPLY,
            confidence=0.9,
            reason="seems relevant to hotel search",
        )
    ]
    reconciled = _run(
        reconcile_judgments(
            memories,
            llm_judgments,
            user_query="Tìm khách sạn ở Sapa",
            domain="hotel",
            domain_action="search_hotels",
            domain_state={},
        )
    )
    assert reconciled[0].label == ApplicabilityLabel.UNCERTAIN
    assert "demoted llm apply" in reconciled[0].reason


def test_reconcile_llm_overridden_high_conf_wins_when_rule_unmatched():
    memories = [
        _memory(
            "window",
            "ưu tiên ghế cửa sổ",
            domain=MemoryDomain.FLIGHT,
            category=MemoryCategory.FLIGHT_PREFERENCE,
        )
    ]
    llm_judgments = [
        ApplicabilityJudgment(
            memory_id="window",
            label=ApplicabilityLabel.OVERRIDDEN,
            confidence=0.85,
            reason="user now wants aisle seat",
        )
    ]
    reconciled = _run(
        reconcile_judgments(
            memories,
            llm_judgments,
            user_query="Đổi sang ghế lối đi giúp tôi",
            domain="flight",
            domain_action="search_one_way",
            domain_state={},
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
    assert "seat capacity (5/7 chỗ) → uncertain" in prompt
    assert "nature/beach/culture tour-type prefs → uncertain" in prompt
    assert "get_hotel_details + bathtub/budget → uncertain" in prompt
    assert "apply as a ranking constraint" not in prompt
    assert "7-seat applies only when the current" not in prompt
    assert "nature pref → apply" not in prompt


class _StubLlmJudge(LlmApplicabilityJudge):
    """LLM-typed judge that returns fixed labels without calling a model."""

    def __init__(self, labels: dict[str, ApplicabilityLabel]) -> None:
        self._labels = labels

    async def judge_batch(
        self,
        *,
        user_query: str,
        domain: str,
        domain_action: str,
        domain_state: dict,
        candidates,
    ):
        return [
            ApplicabilityJudgment(
                memory_id=str(memory.memory_id or ""),
                label=self._labels.get(
                    str(memory.memory_id or ""), ApplicabilityLabel.IRRELEVANT
                ),
                confidence=0.95,
                reason="stub llm",
            )
            for memory in candidates
        ]


def test_memory_service_reconciles_injected_llm_judge_without_llm_kwarg():
    """Eval injects LlmApplicabilityJudge and omits llm=; reconcile must still run."""
    bath = TravelMemory(
        memory_id="bath",
        user_id="user-1",
        memory_text="người dùng thích phòng có bồn tắm",
        category=MemoryCategory.HOTEL_PREFERENCE,
        domain=MemoryDomain.HOTEL,
        evidence_text="bồn tắm",
        source_thread_id="t1",
    )
    beach = TravelMemory(
        memory_id="beach",
        user_id="user-1",
        memory_text="thích gần biển",
        category=MemoryCategory.HOTEL_PREFERENCE,
        domain=MemoryDomain.HOTEL,
        evidence_text="biển",
        source_thread_id="t1",
    )
    settings = Settings(
        database_url="postgresql://user:pass@localhost/db",
        cookie_secret="secret",
        long_term_memory_recall_enabled=True,
        long_term_memory_applicability_judge_enabled=True,
    )
    service = MemoryService(
        settings=settings,
        repository=InMemoryLongTermMemoryRepository([bath, beach]),
        applicability_judge=_StubLlmJudge(
            {
                "bath": ApplicabilityLabel.IRRELEVANT,
                "beach": ApplicabilityLabel.IRRELEVANT,
            }
        ),
    )
    select = _run(
        service.recall_domain_with_applicability(
            user_id="user-1",
            query="Chọn giúp tôi phòng phù hợp nhất",
            domain="hotel",
            domain_action="select_room",
            domain_state={"selected_hotel_id": "hotel_123"},
            # llm deliberately omitted — matches eval suite wiring
        )
    )
    by_id = {item["memory_id"]: item["label"] for item in select.applicability}
    assert by_id["bath"] == "apply"
    assert "bath" in select.recalled_memory_ids

    search = _run(
        service.recall_domain_with_applicability(
            user_id="user-1",
            query="Tìm hotel trung tâm Hà Nội cho chuyến công tác",
            domain="hotel",
            domain_action="search_hotels",
            domain_state={},
        )
    )
    by_id_search = {item["memory_id"]: item["label"] for item in search.applicability}
    assert by_id_search["beach"] == "uncertain"
    assert "beach" in search.recalled_memory_ids
