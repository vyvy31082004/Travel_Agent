import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memory.applicability import ApplicabilityJudgment, ApplicabilityLabel
from memory.constraint_hints import derive_turn_constraints, merge_turn_constraints
from memory.long_term import MemoryCategory, MemoryDomain, TravelMemory


def _memory(memory_id: str, text: str, domain: MemoryDomain) -> TravelMemory:
    return TravelMemory(
        memory_id=memory_id,
        user_id="user-1",
        memory_text=text,
        category=MemoryCategory.HOTEL_PREFERENCE,
        domain=domain,
        evidence_text=text,
        source_thread_id="thread-1",
    )


def test_parse_hotel_budget_range():
    memories = [
        _memory(
            "m_budget",
            "Ngân sách hotel thường 1–2 triệu/đêm",
            MemoryDomain.HOTEL,
        )
    ]
    judgments = [
        ApplicabilityJudgment(
            memory_id="m_budget",
            label=ApplicabilityLabel.APPLY,
            confidence=0.9,
            reason="budget applies",
        )
    ]
    hints = derive_turn_constraints(memories, judgments, domain="hotel")
    assert "price_min=1000000" in hints
    assert "price_max=2000000" in hints


def test_flight_origin_and_cabin_hints():
    memories = [
        _memory(
            "m_departure",
            "Thường bay từ TP.HCM (SGN)",
            MemoryDomain.FLIGHT,
        ),
        _memory(
            "m_economy",
            "Thường bay hạng phổ thông (economy)",
            MemoryDomain.FLIGHT,
        ),
    ]
    judgments = [
        ApplicabilityJudgment(
            memory_id="m_departure",
            label=ApplicabilityLabel.APPLY,
            confidence=0.9,
            reason="origin applies",
        ),
        ApplicabilityJudgment(
            memory_id="m_economy",
            label=ApplicabilityLabel.APPLY,
            confidence=0.9,
            reason="economy applies",
        ),
    ]
    hints = derive_turn_constraints(memories, judgments, domain="flight")
    assert "origin=SGN" in hints
    assert "cabin_class=economy" in hints


def test_car_cate_id_hints_from_user_needs_aliases():
    memories = [
        _memory("m_electric", "Thích xe điện", MemoryDomain.CAR),
        _memory("m_family", "Đi chơi với gia đình", MemoryDomain.CAR),
        _memory("m_auto", "Thích xe số tự động", MemoryDomain.CAR),
    ]
    judgments = [
        ApplicabilityJudgment(
            memory_id="m_electric",
            label=ApplicabilityLabel.APPLY,
            confidence=0.9,
            reason="cateId applies",
        ),
        ApplicabilityJudgment(
            memory_id="m_family",
            label=ApplicabilityLabel.APPLY,
            confidence=0.9,
            reason="cateId applies",
        ),
        ApplicabilityJudgment(
            memory_id="m_auto",
            label=ApplicabilityLabel.UNCERTAIN,
            confidence=0.9,
            reason="transmission soft",
        ),
    ]
    hints = derive_turn_constraints(memories, judgments, domain="car")
    assert "cateId=4" in hints
    assert "cateId=7" in hints
    assert "transmission=automatic" not in hints
    assert "min_seats=7" not in hints


def test_merge_turn_constraints_dedupes():
    merged = merge_turn_constraints(
        ["origin=SGN", "ưu tiên yên tĩnh"],
        ["origin=SGN", "cabin_class=economy"],
    )
    assert merged == ["origin=SGN", "ưu tiên yên tĩnh", "cabin_class=economy"]
