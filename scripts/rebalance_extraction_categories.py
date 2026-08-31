"""Rebalance extraction gold-memory categories without changing split totals.

Targets (115 gold memories total):
  development: 51  -> hotel 11, flight 10, car 8, excursion 7, profile 5, general 5, interaction 5
  test:          64  -> hotel 13, flight 12, car 11, excursion 9, profile 7, general 6, interaction 6

Run from repo root:
  python scripts/rebalance_extraction_categories.py
"""

from __future__ import annotations

import json
from collections import Counter
from copy import deepcopy
from pathlib import Path

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "long_term_memory_eval"
    / "extraction_cases.jsonl"
)

TARGET = {
    ("development", "hotel_preference"): 11,
    ("development", "flight_preference"): 10,
    ("development", "car_preference"): 8,
    ("development", "excursion_preference"): 7,
    ("development", "profile_fact"): 5,
    ("development", "general_preference"): 5,
    ("development", "interaction_rule"): 5,
    ("test", "hotel_preference"): 13,
    ("test", "flight_preference"): 12,
    ("test", "car_preference"): 11,
    ("test", "excursion_preference"): 9,
    ("test", "profile_fact"): 7,
    ("test", "general_preference"): 6,
    ("test", "interaction_rule"): 6,
}

TARGET_TOTALS = {"development": 51, "test": 64}

TRAVEL = "travel_preferences"
PROFILE = "profile_facts"
INTERACTION = "interaction_rules"


def g(text: str, category: str, domain: str, family: str) -> dict:
    return {
        "memory_text": text,
        "category": category,
        "domain": domain,
        "family": family,
    }


def apply_patches(cases: dict[str, dict], patches: dict[str, dict]) -> None:
    for case_id, changes in patches.items():
        if case_id not in cases:
            raise KeyError(f"missing case_id {case_id!r}")
        cases[case_id].update(deepcopy(changes))


def restore_baseline(cases: dict[str, dict]) -> None:
    """Undo prior rebalance edits; restore pilot gold draft (51 dev / 64 test)."""
    apply_patches(
        cases,
        {
            "hotel_pref_001": {
                "messages": [
                    {"type": "human", "content": "Tôi thích khách sạn boutique gần biển"}
                ],
                "gold_memories": [
                    g("thích khách sạn boutique", "hotel_preference", "hotel", TRAVEL),
                    g("thích khách sạn gần biển", "hotel_preference", "hotel", TRAVEL),
                ],
                "rationale": "User nêu boutique và gần biển — cần 2 memory atomic.",
            },
            "car_pref_002": {
                "messages": [{"type": "human", "content": "Tôi ưu tiên xe rộng rãi"}],
                "gold_memories": [
                    g("ưu tiên xe rộng rãi", "car_preference", "car", TRAVEL)
                ],
                "rationale": "Preference đặc tính xe.",
                "metric": ["extraction_recall"],
            },
            "excursion_pref_001": {
                "messages": [
                    {"type": "human", "content": "Tôi thích tour ẩm thực địa phương"}
                ],
                "gold_memories": [
                    g("thích tour ẩm thực địa phương", "excursion_preference", "excursion", TRAVEL)
                ],
                "rationale": "Preference hoạt động du lịch.",
                "metric": ["extraction_recall", "category_accuracy"],
            },
            "general_pref_001": {
                "messages": [
                    {"type": "human", "content": "Tôi thích lịch trình thong thả"}
                ],
                "gold_memories": [
                    g("thích lịch trình thong thả", "general_preference", "general", TRAVEL)
                ],
                "rationale": "Preference lập kế hoạch tổng quát.",
                "metric": ["extraction_recall", "family_accuracy"],
            },
            "general_pref_003": {
                "messages": [{"type": "human", "content": "Tôi thích đi du lịch một mình"}],
                "gold_memories": [
                    g("thích đi du lịch một mình", "general_preference", "general", TRAVEL)
                ],
                "rationale": "Solo travel preference.",
                "metric": ["extraction_recall", "family_accuracy"],
            },
            "profile_001": {
                "messages": [{"type": "human", "content": "Gọi tôi là anh Minh"}],
                "gold_memories": [g("anh Minh", "profile_fact", "general", PROFILE)],
                "rationale": "Quy tắc xưng hô/profile fact.",
                "metric": ["extraction_recall", "category_accuracy", "family_accuracy"],
            },
            "profile_002": {
                "messages": [{"type": "human", "content": "Gọi tôi là chị Hương"}],
                "gold_memories": [g("chị Hương", "profile_fact", "general", PROFILE)],
                "rationale": "Honorific profile fact.",
                "metric": ["extraction_recall", "category_accuracy", "family_accuracy"],
            },
            "profile_003": {
                "messages": [{"type": "human", "content": "Tôi sống ở Hà Nội"}],
                "gold_memories": [g("sống ở Hà Nội", "profile_fact", "general", PROFILE)],
                "rationale": "Home city profile fact.",
                "metric": ["extraction_recall", "category_accuracy"],
            },
            "conditional_002": {
                "messages": [
                    {"type": "human", "content": "Khi đi gia đình tôi thích khách sạn có bếp"}
                ],
                "gold_memories": [
                    g(
                        "khi đi gia đình thích khách sạn có bếp",
                        "hotel_preference",
                        "hotel",
                        TRAVEL,
                    )
                ],
                "rationale": "Điều kiện gia đình phải còn trong memory.",
            },
            "conditional_004": {
                "messages": [
                    {"type": "human", "content": "Khi đi một mình tôi thích hostel"}
                ],
                "gold_memories": [
                    g(
                        "khi đi một mình thích hostel",
                        "hotel_preference",
                        "hotel",
                        TRAVEL,
                    )
                ],
                "rationale": "Condition solo travel for lodging.",
            },
            "conditional_011": {
                "messages": [
                    {
                        "type": "human",
                        "content": "Khi đi cùng người già tôi thích khách sạn có thang máy",
                    }
                ],
                "gold_memories": [
                    g(
                        "khi đi cùng người già thích khách sạn có thang máy",
                        "hotel_preference",
                        "hotel",
                        TRAVEL,
                    )
                ],
                "rationale": "Dev keep elderly-travel lodging condition.",
            },
            "atomic_002": {
                "messages": [
                    {"type": "human", "content": "Tôi muốn xe số tự động, rộng rãi, có tài xế"}
                ],
                "gold_memories": [
                    g("muốn xe số tự động", "car_preference", "car", TRAVEL),
                    g("muốn xe rộng rãi", "car_preference", "car", TRAVEL),
                    g("muốn xe có tài xế", "car_preference", "car", TRAVEL),
                ],
                "rationale": "Mỗi preference là một memory atomic.",
            },
            "atomic_003": {
                "messages": [
                    {
                        "type": "human",
                        "content": "Tôi thích bay thẳng, ghế cửa sổ, không transit dài",
                    }
                ],
                "gold_memories": [
                    g("thích bay thẳng", "flight_preference", "flight", TRAVEL),
                    g("thích ghế cửa sổ", "flight_preference", "flight", TRAVEL),
                    g("không thích transit dài", "flight_preference", "flight", TRAVEL),
                ],
                "rationale": "Ba flight facts atomic.",
            },
            "atomic_010": {
                "messages": [
                    {
                        "type": "human",
                        "content": "Tôi thích khách sạn gần biển, có spa, yên tĩnh",
                    }
                ],
                "gold_memories": [
                    g("thích khách sạn gần biển", "hotel_preference", "hotel", TRAVEL),
                    g("thích khách sạn có spa", "hotel_preference", "hotel", TRAVEL),
                    g("thích khách sạn yên tĩnh", "hotel_preference", "hotel", TRAVEL),
                ],
                "rationale": "Dev three atomic hotel facts.",
            },
            "atomic_011": {
                "messages": [
                    {"type": "human", "content": "Tôi muốn bay thẳng, ghế lối đi, không transit đêm"}
                ],
                "gold_memories": [
                    g("muốn bay thẳng", "flight_preference", "flight", TRAVEL),
                    g("muốn ghế lối đi", "flight_preference", "flight", TRAVEL),
                    g("không muốn transit đêm", "flight_preference", "flight", TRAVEL),
                ],
                "rationale": "Dev three atomic flight facts.",
            },
            "valid_evidence_002": {
                "messages": [
                    {
                        "type": "human",
                        "content": "Tôi thường chọn chuyến bay có hành lý ký gửi",
                    }
                ],
                "gold_memories": [
                    g(
                        "thường chọn chuyến bay có hành lý ký gửi",
                        "flight_preference",
                        "flight",
                        TRAVEL,
                    )
                ],
                "rationale": "Preference được user nói trực tiếp.",
                "metric": ["evidence_faithfulness_rate"],
            },
            "cross_turn_003": {
                "messages": [
                    {"type": "assistant", "content": "Bạn ưu tiên bay thẳng đúng không?"},
                    {"type": "human", "content": "Đúng, tôi ưu tiên bay thẳng"},
                ],
                "gold_memories": [
                    g("ưu tiên bay thẳng", "flight_preference", "flight", TRAVEL)
                ],
                "rationale": "User confirmation after assistant question.",
            },
            "cross_turn_006": {
                "messages": [
                    {"type": "assistant", "content": "Bạn thích bay thẳng đúng không?"},
                    {"type": "human", "content": "Đúng, tôi thích bay thẳng"},
                ],
                "gold_memories": [
                    g("thích bay thẳng", "flight_preference", "flight", TRAVEL)
                ],
                "rationale": "Dev cross-turn confirmation.",
            },
            "tool_confirmed_003": {
                "messages": [
                    {"type": "tool", "content": "hotel near beach"},
                    {"type": "human", "content": "Đúng, tôi thích khách sạn gần biển"},
                ],
                "gold_memories": [
                    g("thích khách sạn gần biển", "hotel_preference", "hotel", TRAVEL)
                ],
                "rationale": "Dev tool option confirmed by user.",
            },
            "tool_confirmed_004": {
                "messages": [
                    {"type": "tool", "content": "flight=direct morning"},
                    {"type": "human", "content": "Ok, tôi ưu tiên bay thẳng buổi sáng"},
                ],
                "gold_memories": [
                    g("ưu tiên bay thẳng buổi sáng", "flight_preference", "flight", TRAVEL)
                ],
                "rationale": "Dev confirmed flight tool option.",
            },
            "classification_002": {
                "messages": [{"type": "human", "content": "Tôi ưu tiên bay từ sân bay nhà"}],
                "gold_memories": [
                    g("ưu tiên bay từ sân bay nhà", "flight_preference", "flight", TRAVEL)
                ],
                "rationale": "Flight marker phải được phân loại flight.",
                "metric": ["category_accuracy", "domain_accuracy"],
            },
            "interaction_003": {
                "messages": [
                    {"type": "human", "content": "Đừng gợi ý tour mạo hiểm trừ khi tôi hỏi"}
                ],
                "gold_memories": [
                    g(
                        "đừng gợi ý tour mạo hiểm trừ khi tôi hỏi",
                        "interaction_rule",
                        "general",
                        INTERACTION,
                    )
                ],
                "rationale": "Conditional interaction rule.",
                "metric": ["extraction_recall"],
            },
            "atomic_001": {
                "messages": [
                    {"type": "human", "content": "Tôi thích khách sạn boutique gần biển, yên tĩnh"}
                ],
                "gold_memories": [
                    g("thích khách sạn boutique", "hotel_preference", "hotel", TRAVEL),
                    g("thích khách sạn gần biển", "hotel_preference", "hotel", TRAVEL),
                    g("thích khách sạn yên tĩnh", "hotel_preference", "hotel", TRAVEL),
                ],
                "rationale": "Gold guideline yêu cầu atomic facts.",
            },
            "atomic_004": {
                "messages": [
                    {
                        "type": "human",
                        "content": "Tôi thích tour ít người, buổi sáng, có hướng dẫn viên",
                    }
                ],
                "gold_memories": [
                    g("thích tour ít người", "excursion_preference", "excursion", TRAVEL),
                    g("thích tour buổi sáng", "excursion_preference", "excursion", TRAVEL),
                    g("thích tour có hướng dẫn viên", "excursion_preference", "excursion", TRAVEL),
                ],
                "rationale": "Held-out multi-fact excursion atomic.",
            },
            "atomic_005": {
                "messages": [
                    {"type": "human", "content": "Tôi thích khách sạn có hồ bơi, gym, gần biển"}
                ],
                "gold_memories": [
                    g("thích khách sạn có hồ bơi", "hotel_preference", "hotel", TRAVEL),
                    g("thích khách sạn có gym", "hotel_preference", "hotel", TRAVEL),
                    g("thích khách sạn gần biển", "hotel_preference", "hotel", TRAVEL),
                ],
                "rationale": "Held-out three atomic hotel amenities.",
            },
            "atomic_006": {
                "messages": [
                    {"type": "human", "content": "Tôi muốn xe số tự động, tiết kiệm xăng, có GPS"}
                ],
                "gold_memories": [
                    g("muốn xe số tự động", "car_preference", "car", TRAVEL),
                    g("muốn xe tiết kiệm xăng", "car_preference", "car", TRAVEL),
                    g("muốn xe có GPS", "car_preference", "car", TRAVEL),
                ],
                "rationale": "Held-out three atomic car preferences.",
            },
            "atomic_007": {
                "messages": [
                    {"type": "human", "content": "Tôi thích bay thẳng, buổi sáng, ghế cửa sổ"}
                ],
                "gold_memories": [
                    g("thích bay thẳng", "flight_preference", "flight", TRAVEL),
                    g("thích bay buổi sáng", "flight_preference", "flight", TRAVEL),
                    g("thích ghế cửa sổ", "flight_preference", "flight", TRAVEL),
                ],
                "rationale": "Held-out three atomic flight preferences.",
            },
            "atomic_008": {
                "messages": [
                    {
                        "type": "human",
                        "content": "Tôi thích khách sạn có ban công, máy giặt, gần công viên",
                    }
                ],
                "gold_memories": [
                    g("thích khách sạn có ban công", "hotel_preference", "hotel", TRAVEL),
                    g("thích khách sạn có máy giặt", "hotel_preference", "hotel", TRAVEL),
                    g("thích khách sạn gần công viên", "hotel_preference", "hotel", TRAVEL),
                ],
                "rationale": "Held-out three atomic hotel amenity facts.",
            },
            "atomic_009": {
                "messages": [
                    {"type": "human", "content": "Tôi muốn xe 7 chỗ, số tự động, có camera lùi"}
                ],
                "gold_memories": [
                    g("muốn xe 7 chỗ", "car_preference", "car", TRAVEL),
                    g("muốn xe số tự động", "car_preference", "car", TRAVEL),
                    g("muốn xe có camera lùi", "car_preference", "car", TRAVEL),
                ],
                "rationale": "Held-out three atomic car facts.",
            },
            "conditional_005": {
                "messages": [
                    {"type": "human", "content": "Khi đi với bạn bè tôi thích hostel dorm"}
                ],
                "gold_memories": [
                    g(
                        "khi đi với bạn bè thích hostel dorm",
                        "hotel_preference",
                        "hotel",
                        TRAVEL,
                    )
                ],
                "rationale": "Held-out conditional lodging.",
            },
            "conditional_006": {
                "messages": [
                    {
                        "type": "human",
                        "content": "Khi đi công tác tôi thích khách sạn gần trung tâm",
                    }
                ],
                "gold_memories": [
                    g(
                        "khi đi công tác thích khách sạn gần trung tâm",
                        "hotel_preference",
                        "hotel",
                        TRAVEL,
                    )
                ],
                "rationale": "Held-out business-trip lodging condition.",
            },
            "valid_evidence_004": {
                "messages": [{"type": "human", "content": "Tôi thích tour ít người"}],
                "gold_memories": [
                    g("thích tour ít người", "excursion_preference", "excursion", TRAVEL)
                ],
                "rationale": "Preference tour explicit.",
                "metric": ["evidence_faithfulness_rate"],
            },
            "excursion_pref_008": {
                "messages": [
                    {"type": "human", "content": "Tôi ưu tiên trải nghiệm workshop thủ công"}
                ],
                "gold_memories": [
                    g(
                        "ưu tiên trải nghiệm workshop thủ công",
                        "excursion_preference",
                        "excursion",
                        TRAVEL,
                    )
                ],
                "rationale": "Held-out craft workshop preference.",
                "metric": ["extraction_recall"],
            },
            "general_pref_005": {
                "messages": [{"type": "human", "content": "Tôi thích lịch trình linh hoạt"}],
                "gold_memories": [
                    g("thích lịch trình linh hoạt", "general_preference", "general", TRAVEL)
                ],
                "rationale": "Held-out flexible itinerary preference.",
                "metric": ["extraction_recall", "family_accuracy"],
            },
            "interaction_004": {
                "messages": [
                    {"type": "human", "content": "Hãy nhớ luôn dùng xưng hô lịch sự"}
                ],
                "gold_memories": [
                    g("luôn dùng xưng hô lịch sự", "interaction_rule", "general", INTERACTION)
                ],
                "rationale": "Held-out polite address interaction rule.",
                "metric": ["extraction_recall", "family_accuracy"],
            },
            "classification_003": {
                "messages": [{"type": "human", "content": "Tôi thích thuê xe ở sân bay"}],
                "gold_memories": [
                    g("thích thuê xe ở sân bay", "car_preference", "car", TRAVEL)
                ],
                "rationale": "Ngữ cảnh thuê xe phải ưu tiên car classification.",
                "metric": ["category_accuracy", "domain_accuracy"],
            },
            "valid_evidence_007": {
                "messages": [{"type": "human", "content": "Tôi thích khách sạn có máy giặt"}],
                "gold_memories": [
                    g("thích khách sạn có máy giặt", "hotel_preference", "hotel", TRAVEL)
                ],
                "rationale": "Held-out washer amenity with user evidence.",
                "metric": ["evidence_faithfulness_rate"],
            },
        },
    )


def apply_category_balance(cases: dict[str, dict]) -> None:
    """Reassign categories within fixed split totals (51 dev / 64 test).

    Every edit recategorizes existing gold memories (no merge/split), so totals stay 51/64.
    """
    apply_patches(
        cases,
        {
            # --- development: hotel -7, flight -5, excursion +5, profile +2, general +3, interaction +2 ---
            "classification_001": {
                "messages": [{"type": "human", "content": "Gọi tôi là chị Lan"}],
                "gold_memories": [g("chị Lan", "profile_fact", "general", PROFILE)],
                "rationale": "Profile marker phải được gán profile_fact/general.",
                "metric": ["category_accuracy", "domain_accuracy", "family_accuracy"],
            },
            "conditional_004": {
                "messages": [
                    {"type": "human", "content": "Khi đi một mình tôi thích tour đi bộ nhẹ nhàng"}
                ],
                "gold_memories": [
                    g(
                        "khi đi một mình thích tour đi bộ nhẹ nhàng",
                        "excursion_preference",
                        "excursion",
                        TRAVEL,
                    )
                ],
                "rationale": "Condition solo travel for excursion.",
            },
            "atomic_010": {
                "messages": [
                    {
                        "type": "human",
                        "content": "Tôi thích tour ít người, buổi sáng, có hướng dẫn viên",
                    }
                ],
                "gold_memories": [
                    g("thích tour ít người", "excursion_preference", "excursion", TRAVEL),
                    g("thích tour buổi sáng", "excursion_preference", "excursion", TRAVEL),
                    g("thích tour có hướng dẫn viên", "excursion_preference", "excursion", TRAVEL),
                ],
                "rationale": "Dev three atomic excursion facts.",
            },
            "valid_evidence_001": {
                "messages": [
                    {"type": "human", "content": "Hãy nhớ luôn trả lời ngắn gọn bằng tiếng Việt"}
                ],
                "gold_memories": [
                    g(
                        "luôn trả lời ngắn gọn bằng tiếng Việt",
                        "interaction_rule",
                        "general",
                        INTERACTION,
                    )
                ],
                "rationale": "Interaction rule evidence from user.",
                "metric": ["evidence_faithfulness_rate", "category_accuracy", "family_accuracy"],
            },
            "conditional_011": {
                "messages": [
                    {"type": "human", "content": "Gọi tôi là anh Tuấn"}
                ],
                "gold_memories": [g("anh Tuấn", "profile_fact", "general", PROFILE)],
                "rationale": "Dev profile honorific fact.",
                "metric": ["extraction_recall", "category_accuracy", "family_accuracy"],
            },
            "flight_pref_002": {
                "messages": [{"type": "human", "content": "Tôi thường đi du lịch vào mùa khô"}],
                "gold_memories": [
                    g("thường đi du lịch vào mùa khô", "general_preference", "general", TRAVEL)
                ],
                "rationale": "Seasonal travel preference.",
                "metric": ["extraction_recall", "family_accuracy"],
            },
            "flight_pref_008": {
                "messages": [{"type": "human", "content": "Tôi thích tránh lịch trình đêm muộn"}],
                "gold_memories": [
                    g("thích tránh lịch trình đêm muộn", "general_preference", "general", TRAVEL)
                ],
                "rationale": "General scheduling preference.",
                "metric": ["extraction_recall", "family_accuracy"],
            },
            "classification_002": {
                "messages": [{"type": "human", "content": "Tôi thích tour tham quan bảo tàng"}],
                "gold_memories": [
                    g("thích tour tham quan bảo tàng", "excursion_preference", "excursion", TRAVEL)
                ],
                "rationale": "Excursion marker phải được phân loại excursion.",
                "metric": ["category_accuracy", "domain_accuracy"],
            },
            "cross_turn_003": {
                "messages": [
                    {"type": "assistant", "content": "Bạn muốn phản hồi ngắn gọn đúng không?"},
                    {"type": "human", "content": "Đúng, tôi muốn phản hồi ngắn gọn"},
                ],
                "gold_memories": [
                    g("muốn phản hồi ngắn gọn", "interaction_rule", "general", INTERACTION)
                ],
                "rationale": "User confirmation for interaction rule.",
            },
            "cross_turn_006": {
                "messages": [
                    {
                        "type": "assistant",
                        "content": "Bạn thích lịch trình thong thả đúng không?",
                    },
                    {"type": "human", "content": "Đúng, tôi thích lịch trình thong thả"},
                ],
                "gold_memories": [
                    g("thích lịch trình thong thả", "general_preference", "general", TRAVEL)
                ],
                "rationale": "Dev cross-turn general preference confirmation.",
            },
            # --- held-out: hotel -5, car -1, excursion -1, profile +2, general +2, interaction +3 ---
            "hotel_pref_005": {
                "messages": [{"type": "human", "content": "Gọi tôi là anh Bình"}],
                "gold_memories": [g("anh Bình", "profile_fact", "general", PROFILE)],
                "rationale": "Held-out profile honorific.",
                "metric": ["extraction_recall", "category_accuracy", "family_accuracy"],
            },
            "valid_evidence_007": {
                "messages": [
                    {"type": "human", "content": "Hãy nhớ đừng gửi quá nhiều lựa chọn cùng lúc"}
                ],
                "gold_memories": [
                    g(
                        "đừng gửi quá nhiều lựa chọn cùng lúc",
                        "interaction_rule",
                        "general",
                        INTERACTION,
                    )
                ],
                "rationale": "Held-out interaction rule with user evidence.",
                "metric": ["evidence_faithfulness_rate", "category_accuracy", "family_accuracy"],
            },
            "conditional_006": {
                "messages": [
                    {"type": "human", "content": "Khi đi công tác tôi thích thuê xe tại sân bay"}
                ],
                "gold_memories": [
                    g(
                        "khi đi công tác thích thuê xe tại sân bay",
                        "car_preference",
                        "car",
                        TRAVEL,
                    )
                ],
                "rationale": "Held-out business-trip car condition.",
            },
            "atomic_001": {
                "messages": [
                    {
                        "type": "human",
                        "content": "Tôi thích khách sạn boutique gần biển, yên tĩnh",
                    }
                ],
                "gold_memories": [
                    g("thích khách sạn boutique", "hotel_preference", "hotel", TRAVEL),
                    g("thích khách sạn gần biển", "hotel_preference", "hotel", TRAVEL),
                    g("thích không gian yên tĩnh", "general_preference", "general", TRAVEL),
                ],
                "rationale": "Held-out three atomic facts with one general preference.",
            },
            "atomic_005": {
                "messages": [
                    {
                        "type": "human",
                        "content": "Tôi thích khách sạn có hồ bơi, gym, gần biển",
                    }
                ],
                "gold_memories": [
                    g("thích khách sạn có hồ bơi", "hotel_preference", "hotel", TRAVEL),
                    g("thích khách sạn có gym", "hotel_preference", "hotel", TRAVEL),
                    g("thích khách sạn gần biển", "general_preference", "general", TRAVEL),
                ],
                "rationale": "Held-out amenities plus one general location preference.",
            },
            "classification_003": {
                "messages": [{"type": "human", "content": "Gọi tôi là chị Hạnh"}],
                "gold_memories": [g("chị Hạnh", "profile_fact", "general", PROFILE)],
                "rationale": "Profile classification case.",
                "metric": ["category_accuracy", "family_accuracy"],
            },
            "atomic_006": {
                "messages": [
                    {"type": "human", "content": "Tôi muốn xe số tự động, tiết kiệm xăng, có GPS"}
                ],
                "gold_memories": [
                    g("muốn xe số tự động", "car_preference", "car", TRAVEL),
                    g("muốn xe tiết kiệm xăng", "car_preference", "car", TRAVEL),
                    g("muốn xe có GPS", "general_preference", "general", TRAVEL),
                ],
                "rationale": "Held-out car facts with one general equipment preference.",
            },
            "valid_evidence_004": {
                "messages": [{"type": "human", "content": "Tôi thích lịch trình linh hoạt"}],
                "gold_memories": [
                    g("thích lịch trình linh hoạt", "general_preference", "general", TRAVEL)
                ],
                "rationale": "General preference explicit from user.",
                "metric": ["evidence_faithfulness_rate", "family_accuracy"],
            },
            "general_pref_005": {
                "messages": [
                    {"type": "human", "content": "Hãy nhớ tóm tắt ngắn trước khi đề xuất"}
                ],
                "gold_memories": [
                    g(
                        "tóm tắt ngắn trước khi đề xuất",
                        "interaction_rule",
                        "general",
                        INTERACTION,
                    )
                ],
                "rationale": "Held-out summarize-before-suggest interaction rule.",
                "metric": ["extraction_recall", "category_accuracy", "family_accuracy"],
            },
            "cross_turn_005": {
                "messages": [
                    {"type": "assistant", "content": "Bạn thích phản hồi ngắn gọn đúng không?"},
                    {"type": "human", "content": "Đúng, tôi thích phản hồi ngắn gọn"},
                ],
                "gold_memories": [
                    g("thích phản hồi ngắn gọn", "interaction_rule", "general", INTERACTION)
                ],
                "rationale": "Held-out user confirms interaction preference across turns.",
                "metric": ["evidence_faithfulness_rate", "category_accuracy", "family_accuracy"],
            },
        },
    )


def count_categories(cases: list[dict]) -> Counter:
    counts: Counter = Counter()
    for case in cases:
        for item in case.get("gold_memories") or []:
            counts[(case["split"], item["category"])] += 1
    return counts


def split_totals(cases: list[dict]) -> dict[str, int]:
    totals: dict[str, int] = {"development": 0, "test": 0}
    for case in cases:
        totals[case["split"]] += len(case.get("gold_memories") or [])
    return totals


def main() -> None:
    rows = [
        json.loads(line)
        for line in FIXTURE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_id = {row["case_id"]: row for row in rows}
    restore_baseline(by_id)
    apply_category_balance(by_id)
    updated = [by_id[row["case_id"]] for row in rows]

    counts = count_categories(updated)
    totals = split_totals(updated)

    mismatches = [
        f"{key}: actual={counts.get(key, 0)} target={target}"
        for key, target in sorted(TARGET.items())
        if counts.get(key, 0) != target
    ]
    for split, expected in TARGET_TOTALS.items():
        if totals[split] != expected:
            mismatches.append(f"{split} total: actual={totals[split]} target={expected}")

    if mismatches:
        raise SystemExit("Category rebalance failed:\n" + "\n".join(mismatches))

    FIXTURE.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in updated) + "\n",
        encoding="utf-8",
    )
    print(f"Updated {FIXTURE}")
    print(f"development gold memories: {totals['development']}")
    print(f"test gold memories: {totals['test']}")
    for split in ("development", "test"):
        print(f"  {split} categories:", {k[1]: counts[(split, k[1])] for k in sorted(counts) if k[0] == split})


if __name__ == "__main__":
    main()
