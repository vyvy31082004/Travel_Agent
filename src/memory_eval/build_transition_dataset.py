"""Build transition_cases.jsonl (150 cases) and transition_split_manifest.json.

Run from repo root or src:
  python -m memory_eval.build_transition_dataset
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURE_DIR = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "long_term_memory_eval"
)


def _mem(
    memory_id: str,
    *,
    memory_text: str,
    category: str,
    domain: str,
    evidence_text: str,
    user_id: str = "user-1",
    thread_id: str = "t1",
    status: str = "active",
    condition: str | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "memory_id": memory_id,
        "user_id": user_id,
        "memory_text": memory_text,
        "category": category,
        "domain": domain,
        "evidence_text": evidence_text,
        "source_thread_id": thread_id,
        "status": status,
    }
    if condition is not None:
        row["condition"] = condition
    return row


def _cand(
    *,
    memory_text: str,
    category: str,
    domain: str,
    evidence_text: str,
    user_id: str = "user-1",
    thread_id: str = "t2",
    condition: str | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "user_id": user_id,
        "memory_text": memory_text,
        "category": category,
        "domain": domain,
        "evidence_text": evidence_text,
        "source_thread_id": thread_id,
    }
    if condition is not None:
        row["condition"] = condition
    return row


def _case(
    case_id: str,
    *,
    split: str,
    requirement_id: str,
    risk: str,
    gold_action: str,
    existing: list[dict[str, Any]],
    candidate: dict[str, Any],
    rationale: str,
    code_path: list[str],
    metric: list[str] | None = None,
) -> dict[str, Any]:
    metrics = metric or ["transition_accuracy"]
    if gold_action == "supersede" and "supersession_correctness" not in metrics:
        metrics = [*metrics, "supersession_correctness"]
    return {
        "case_id": case_id,
        "requirement_id": requirement_id,
        "risk": risk,
        "split": split,
        "existing": existing,
        "candidate": candidate,
        "gold_action": gold_action,
        "rationale": rationale,
        "code_path": code_path,
        "metric": metrics,
    }


def build_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    # --- DUP / NOOP (18): 12 development, 6 test ---
    dup_specs = [
        ("dup_001", "development", "hotel", "hotel_preference", "hotel",
         "thích khách sạn boutique gần biển", "Tôi thích khách sạn boutique gần biển"),
        ("dup_002", "development", "flight", "flight_preference", "flight",
         "ưu tiên bay thẳng", "Tôi ưu tiên bay thẳng"),
        ("dup_003", "development", "car", "car_preference", "car",
         "thích thuê xe số tự động", "Tôi thích thuê xe số tự động"),
        ("dup_004", "development", "excursion", "excursion_preference", "excursion",
         "thích tour ẩm thực địa phương", "Tôi thích tour ẩm thực địa phương"),
        ("dup_005", "development", "general", "general_preference", "general",
         "thích lịch trình thong thả", "Tôi thích lịch trình thong thả"),
        ("dup_006", "development", "profile", "profile_fact", "general",
         "anh Minh", "Gọi tôi là anh Minh"),
        ("dup_007", "development", "hotel", "hotel_preference", "hotel",
         "thường chọn resort yên tĩnh", "Tôi thường chọn resort yên tĩnh"),
        ("dup_008", "development", "flight", "flight_preference", "flight",
         "ưu tiên chuyến bay buổi tối", "Tôi ưu tiên chuyến bay buổi tối"),
        ("dup_009", "development", "car", "car_preference", "car",
         "ưu tiên xe rộng rãi", "Tôi ưu tiên xe rộng rãi"),
        ("dup_010", "development", "hotel", "hotel_preference", "hotel",
         "thích phòng yên tĩnh", "Hãy nhớ là tôi thích phòng yên tĩnh"),
        ("dup_011", "development", "flight", "flight_preference", "flight",
         "thường bay từ sân bay nhà là SGN", "Tôi thường bay từ sân bay nhà là SGN"),
        ("dup_012", "development", "interaction", "interaction_rule", "general",
         "đừng hỏi lại những thông tin tôi đã cung cấp",
         "Hãy nhớ đừng hỏi lại những thông tin tôi đã cung cấp"),
    ]
    for case_id, split, mid, cat, dom, text, evidence in dup_specs:
        cases.append(
            _case(
                case_id,
                split=split,
                requirement_id="REQ-TRANS-DUP",
                risk="duplicate_insert",
                gold_action="noop",
                existing=[
                    _mem(f"old-{mid}", memory_text=text, category=cat, domain=dom,
                         evidence_text=evidence, thread_id="t1")
                ],
                candidate=_cand(
                    memory_text=text, category=cat, domain=dom,
                    evidence_text=evidence, thread_id="t2",
                ),
                rationale="Candidate trùng memory active sau chuẩn hóa → noop.",
                code_path=["calculate_transition", "_normalize_statement"],
            )
        )

    # --- CONFLICT SUPERSEDE (18): 12 development, 6 test ---
    conflict_specs = [
        ("conflict_001", "development",
         "thích khách sạn boutique gần biển", "không thích khách sạn boutique gần biển",
         "Tôi thích khách sạn boutique gần biển",
         "Tôi không thích khách sạn boutique gần biển",
         "hotel_preference", "hotel"),
        ("conflict_002", "development",
         "ưu tiên bay thẳng", "không thích bay thẳng",
         "Tôi ưu tiên bay thẳng", "Tôi không thích bay thẳng",
         "flight_preference", "flight"),
        ("conflict_003", "development",
         "thích thuê xe số tự động", "không thích thuê xe số tự động",
         "Tôi thích thuê xe số tự động", "Tôi không thích thuê xe số tự động",
         "car_preference", "car"),
        ("conflict_004", "development",
         "thích tour ẩm thực địa phương", "không thích tour ẩm thực địa phương",
         "Tôi thích tour ẩm thực địa phương",
         "Tôi không thích tour ẩm thực địa phương",
         "excursion_preference", "excursion"),
        ("conflict_005", "development",
         "thích lịch trình thong thả", "không thích lịch trình thong thả",
         "Tôi thích lịch trình thong thả", "Tôi không thích lịch trình thong thả",
         "general_preference", "general"),
        ("conflict_006", "development",
         "thích resort yên tĩnh", "không thích resort yên tĩnh",
         "Tôi thích resort yên tĩnh", "Tôi không thích resort yên tĩnh",
         "hotel_preference", "hotel"),
        ("conflict_007", "development",
         "ưu tiên chuyến bay buổi tối", "không thích chuyến bay buổi tối",
         "Tôi ưu tiên chuyến bay buổi tối", "Tôi không thích chuyến bay buổi tối",
         "flight_preference", "flight"),
        ("conflict_008", "development",
         "ưu tiên xe rộng rãi", "không thích xe rộng rãi",
         "Tôi ưu tiên xe rộng rãi", "Tôi không thích xe rộng rãi",
         "car_preference", "car"),
        ("conflict_009", "development",
         "thích phòng yên tĩnh", "không thích phòng yên tĩnh",
         "Tôi thích phòng yên tĩnh", "Tôi không thích phòng yên tĩnh",
         "hotel_preference", "hotel"),
        ("conflict_010", "development",
         "muốn ghế cạnh cửa sổ", "không thích ghế cạnh cửa sổ",
         "Tôi muốn ghế cạnh cửa sổ", "Tôi không thích ghế cạnh cửa sổ",
         "flight_preference", "flight"),
        ("conflict_011", "development",
         "thích homestay có bữa sáng", "không thích homestay có bữa sáng",
         "Tôi thích homestay có bữa sáng", "Tôi không thích homestay có bữa sáng",
         "hotel_preference", "hotel"),
        ("conflict_012", "development",
         "ưu tiên hoạt động tham quan nhẹ nhàng",
         "không thích hoạt động tham quan nhẹ nhàng",
         "Tôi ưu tiên hoạt động tham quan nhẹ nhàng",
         "Tôi không thích hoạt động tham quan nhẹ nhàng",
         "excursion_preference", "excursion"),
    ]
    for i, (case_id, split, old_text, new_text, old_ev, new_ev, cat, dom) in enumerate(
        conflict_specs, start=1
    ):
        cases.append(
            _case(
                case_id,
                split=split,
                requirement_id="REQ-TRANS-CONFLICT",
                risk="preference_conflict",
                gold_action="supersede",
                existing=[
                    _mem(
                        f"old-conflict-{i}",
                        memory_text=old_text,
                        category=cat,
                        domain=dom,
                        evidence_text=old_ev,
                    )
                ],
                candidate=_cand(
                    memory_text=new_text,
                    category=cat,
                    domain=dom,
                    evidence_text=new_ev,
                ),
                rationale="Cùng category/domain, polarity đối lập → supersede.",
                code_path=["calculate_transition", "_memories_conflict"],
            )
        )

    # --- CONDITION SUPERSEDE (10): 6 development, 4 test ---
    condition_specs = [
        ("condition_001", "development",
         "ưu tiên economy khi đi du lịch", "không thích economy khi đi du lịch",
         "khi đi du lịch", "Tôi ưu tiên economy khi đi du lịch",
         "Tôi không thích economy khi đi du lịch",
         "flight_preference", "flight"),
        ("condition_002", "development",
         "muốn business khi đi công tác", "không thích business khi đi công tác",
         "khi đi công tác", "Tôi muốn business khi đi công tác",
         "Tôi không thích business khi đi công tác",
         "flight_preference", "flight"),
        ("condition_003", "development",
         "thích khách sạn có bếp khi đi gia đình",
         "không thích khách sạn có bếp khi đi gia đình",
         "khi đi gia đình", "Khi đi gia đình tôi thích khách sạn có bếp",
         "Khi đi gia đình tôi không thích khách sạn có bếp",
         "hotel_preference", "hotel"),
        ("condition_004", "development",
         "ưu tiên xe 7 chỗ khi đi đông người",
         "không thích xe 7 chỗ khi đi đông người",
         "khi đi đông người", "Tôi ưu tiên xe 7 chỗ khi đi đông người",
         "Tôi không thích xe 7 chỗ khi đi đông người",
         "car_preference", "car"),
        ("condition_005", "development",
         "thích tour ngắn khi đi cuối tuần",
         "không thích tour ngắn khi đi cuối tuần",
         "khi đi cuối tuần", "Tôi thích tour ngắn khi đi cuối tuần",
         "Tôi không thích tour ngắn khi đi cuối tuần",
         "excursion_preference", "excursion"),
        ("condition_006", "development",
         "ưu tiên lịch trình thong thả khi đi nghỉ",
         "không thích lịch trình thong thả khi đi nghỉ",
         "khi đi nghỉ", "Tôi ưu tiên lịch trình thong thả khi đi nghỉ",
         "Tôi không thích lịch trình thong thả khi đi nghỉ",
         "general_preference", "general"),
    ]
    for i, (case_id, split, old_text, new_text, cond, old_ev, new_ev, cat, dom) in enumerate(
        condition_specs, start=1
    ):
        cases.append(
            _case(
                case_id,
                split=split,
                requirement_id="REQ-TRANS-CONDITION",
                risk="updated_condition",
                gold_action="supersede",
                existing=[
                    _mem(
                        f"old-cond-{i}",
                        memory_text=old_text,
                        category=cat,
                        domain=dom,
                        evidence_text=old_ev,
                        condition=cond,
                    )
                ],
                candidate=_cand(
                    memory_text=new_text,
                    category=cat,
                    domain=dom,
                    evidence_text=new_ev,
                    condition=cond,
                ),
                rationale="Cùng category/domain, điều kiện/preference đổi → supersede.",
                code_path=["calculate_transition", "_memories_conflict"],
            )
        )

    # --- SENSITIVE / TOOL REJECT (16): 10 development, 6 test ---
    sensitive_specs = [
        ("sensitive_001", "development", "mật khẩu của tôi là abc",
         "Hãy nhớ mật khẩu của tôi là abc", "profile_fact", "general",
         "password_leak"),
        ("sensitive_002", "development", "password của tôi là secret123",
         "Please remember password của tôi là secret123", "profile_fact", "general",
         "password_leak"),
        ("sensitive_003", "development", "số hộ chiếu của tôi là B1234567",
         "Hãy nhớ số hộ chiếu của tôi là B1234567", "profile_fact", "general",
         "passport_leak"),
        ("sensitive_004", "development", "passport number is A998877",
         "Remember that passport number is A998877", "profile_fact", "general",
         "passport_leak"),
        ("sensitive_005", "development", "thẻ tín dụng của tôi là 4111111111111111",
         "Hãy nhớ thẻ tín dụng của tôi là 4111111111111111", "profile_fact", "general",
         "card_leak"),
        ("sensitive_006", "development", "credit card ending 4242",
         "Please remember my credit card ending 4242", "profile_fact", "general",
         "card_leak"),
        ("sensitive_007", "development", "cvv của tôi là 123",
         "Hãy nhớ cvv của tôi là 123", "profile_fact", "general",
         "cvv_leak"),
        ("sensitive_008", "development", "hotel item_id=H99 giá 1500000",
         "Kết quả search_id=abc total_results=12 item_id=H99", "hotel_preference",
         "hotel", "tool_only"),
        ("sensitive_009", "development", "flight item_id=F12",
         "Tool trả displayed_item_ids=[F12] search_id=xyz", "flight_preference",
         "flight", "tool_only"),
        ("sensitive_010", "development", "car item_id=C3",
         "API payload item_id=C3 total_results=3", "car_preference", "car",
         "tool_only"),
    ]
    for case_id, split, text, evidence, cat, dom, risk in sensitive_specs:
        cases.append(
            _case(
                case_id,
                split=split,
                requirement_id="REQ-TRANS-SENSITIVE",
                risk=risk,
                gold_action="reject",
                existing=[],
                candidate=_cand(
                    memory_text=text,
                    category=cat,
                    domain=dom,
                    evidence_text=evidence,
                    thread_id="t1",
                ),
                rationale="Evidence nhạy cảm hoặc tool-only → reject.",
                code_path=["validate_memory_candidate"],
            )
        )

    # --- AMBIGUOUS REJECT (12): 8 development, 4 test ---
    ambiguous_specs = [
        ("ambiguous_001", "development", "thích khách sạn gần biển",
         "Có thể tôi thích khách sạn gần biển", "hotel_preference", "hotel"),
        ("ambiguous_002", "development", "ưu tiên bay thẳng",
         "Maybe tôi ưu tiên bay thẳng", "flight_preference", "flight"),
        ("ambiguous_003", "development", "thích xe số tự động",
         "Perhaps tôi thích xe số tự động", "car_preference", "car"),
        ("ambiguous_004", "development", "thích tour ẩm thực",
         "Tôi không chắc mình thích tour ẩm thực", "excursion_preference",
         "excursion"),
        ("ambiguous_005", "development", "thích lịch trình thong thả",
         "Có thể tôi thích lịch trình thong thả", "general_preference", "general"),
        ("ambiguous_006", "development", "thích resort yên tĩnh",
         "Maybe tôi thích resort yên tĩnh", "hotel_preference", "hotel"),
        ("ambiguous_007", "development", "ưu tiên ghế cửa sổ",
         "Có thể tôi ưu tiên ghế cửa sổ", "flight_preference", "flight"),
        ("ambiguous_008", "development", "thích xe có tài xế",
         "Tôi không chắc mình thích xe có tài xế", "car_preference", "car"),
    ]
    for case_id, split, text, evidence, cat, dom in ambiguous_specs:
        cases.append(
            _case(
                case_id,
                split=split,
                requirement_id="REQ-TRANS-AMBIGUOUS",
                risk="ambiguous",
                gold_action="reject",
                existing=[],
                candidate=_cand(
                    memory_text=text,
                    category=cat,
                    domain=dom,
                    evidence_text=evidence,
                    thread_id="t1",
                ),
                rationale="Evidence mơ hồ → reject.",
                code_path=["validate_memory_candidate", "_is_ambiguous"],
            )
        )

    # --- INSERT (26): 17 development, 9 test ---
    insert_specs = [
        ("insert_001", "development", "thích khách sạn boutique gần biển",
         "Tôi thích khách sạn boutique gần biển", "hotel_preference", "hotel", []),
        ("insert_002", "development", "ưu tiên bay thẳng",
         "Tôi ưu tiên bay thẳng", "flight_preference", "flight", []),
        ("insert_003", "development", "thích thuê xe số tự động",
         "Tôi thích thuê xe số tự động", "car_preference", "car", []),
        ("insert_004", "development", "thích tour ẩm thực địa phương",
         "Tôi thích tour ẩm thực địa phương", "excursion_preference", "excursion",
         []),
        ("insert_005", "development", "thích lịch trình thong thả",
         "Tôi thích lịch trình thong thả", "general_preference", "general", []),
        ("insert_006", "development", "anh Minh",
         "Gọi tôi là anh Minh", "profile_fact", "general", []),
        ("insert_007", "development", "thường chọn resort yên tĩnh",
         "Tôi thường chọn resort yên tĩnh", "hotel_preference", "hotel",
         [_mem("other-flight-1", memory_text="ưu tiên bay thẳng",
               category="flight_preference", domain="flight",
               evidence_text="Tôi ưu tiên bay thẳng")]),
        ("insert_008", "development", "ưu tiên homestay có bữa sáng",
         "Tôi ưu tiên homestay có bữa sáng", "hotel_preference", "hotel", []),
        ("insert_009", "development", "thường bay từ sân bay nhà là SGN",
         "Tôi thường bay từ sân bay nhà là SGN", "flight_preference", "flight", []),
        ("insert_010", "development", "ưu tiên xe rộng rãi",
         "Tôi ưu tiên xe rộng rãi", "car_preference", "car", []),
        ("insert_011", "development", "ưu tiên hoạt động tham quan nhẹ nhàng",
         "Tôi ưu tiên hoạt động tham quan nhẹ nhàng", "excursion_preference",
         "excursion", []),
        ("insert_012", "development", "đừng hỏi lại những thông tin tôi đã cung cấp",
         "Hãy nhớ đừng hỏi lại những thông tin tôi đã cung cấp",
         "interaction_rule", "general", []),
        ("insert_013", "development", "thích phòng yên tĩnh",
         "Hãy nhớ là tôi thích phòng yên tĩnh", "hotel_preference", "hotel", []),
        ("insert_014", "development", "ưu tiên chuyến bay buổi tối",
         "Tôi ưu tiên chuyến bay buổi tối", "flight_preference", "flight", []),
        ("insert_015", "development", "thường thuê xe có tài xế",
         "Tôi thường thuê xe có tài xế", "car_preference", "car", []),
        ("insert_016", "development", "thường đi cùng gia đình có trẻ nhỏ",
         "Tôi thường đi cùng gia đình có trẻ nhỏ", "general_preference", "general",
         []),
        ("insert_017", "development", "thích khách sạn gần hội nghị",
         "Tôi thích khách sạn gần hội nghị", "hotel_preference", "hotel",
         [_mem("other-car-1", memory_text="thích thuê xe số tự động",
               category="car_preference", domain="car",
               evidence_text="Tôi thích thuê xe số tự động")]),
    ]
    for case_id, split, text, evidence, cat, dom, existing in insert_specs:
        cases.append(
            _case(
                case_id,
                split=split,
                requirement_id="REQ-TRANS-INSERT",
                risk="false_noop",
                gold_action="insert",
                existing=existing,
                candidate=_cand(
                    memory_text=text,
                    category=cat,
                    domain=dom,
                    evidence_text=evidence,
                    thread_id="t1",
                ),
                rationale="Candidate hợp lệ, không trùng/conflict → insert.",
                code_path=["calculate_transition"],
            )
        )

    cases.extend(build_heldout_cases())
    return cases


def build_heldout_cases() -> list[dict[str, Any]]:
    """85 held-out cases: ~half lexical-easy (expect pass), ~half policy-hard (expect miss).

    Distribution mirrors extraction held-out size (65/85):
      DUP 15, CONFLICT 15, CONDITION 10, SENSITIVE 15, AMBIGUOUS 10, INSERT 20.
    """
    held: list[dict[str, Any]] = []

    # --- DUP: 7 easy exact + 8 hard paraphrase ---
    easy_dups = [
        ("dup_013", "thích khách sạn gần trung tâm",
         "Tôi thích khách sạn gần trung tâm", "hotel_preference", "hotel"),
        ("dup_014", "muốn ghế cạnh cửa sổ",
         "Tôi muốn ghế cạnh cửa sổ", "flight_preference", "flight"),
        ("dup_015", "thường thuê xe có tài xế",
         "Tôi thường thuê xe có tài xế", "car_preference", "car"),
        ("dup_019", "thích homestay ấm cúng",
         "Tôi thích homestay ấm cúng", "hotel_preference", "hotel"),
        ("dup_020", "ưu tiên bay thẳng",
         "Tôi ưu tiên bay thẳng", "flight_preference", "flight"),
        ("dup_021", "thích xe số tự động",
         "Tôi thích xe số tự động", "car_preference", "car"),
        ("dup_022", "thích tour ẩm thực",
         "Tôi thích tour ẩm thực", "excursion_preference", "excursion"),
    ]
    for case_id, text, evidence, cat, dom in easy_dups:
        held.append(
            _case(
                case_id,
                split="test",
                requirement_id="REQ-TRANS-DUP",
                risk="duplicate_insert",
                gold_action="noop",
                existing=[
                    _mem(
                        f"old-{case_id}",
                        memory_text=text,
                        category=cat,
                        domain=dom,
                        evidence_text=evidence,
                    )
                ],
                candidate=_cand(
                    memory_text=text, category=cat, domain=dom, evidence_text=evidence
                ),
                rationale="Exact duplicate → noop (lexical easy).",
                code_path=["calculate_transition", "_normalize_statement"],
            )
        )
    hard_dups = [
        ("dup_016", "thích tour ẩm thực địa phương",
         "Tôi thích tour ẩm thực địa phương",
         "ưu tiên food tour địa phương", "Tôi ưu tiên food tour địa phương",
         "excursion_preference", "excursion"),
        ("dup_017", "thích lịch trình thong thả", "Tôi thích lịch trình thong thả",
         "ưu tiên lịch trình chậm rãi", "Tôi ưu tiên lịch trình chậm rãi",
         "general_preference", "general"),
        ("dup_018", "anh Minh", "Gọi tôi là anh Minh",
         "xưng hô với tôi là anh Minh", "Hãy nhớ xưng hô với tôi là anh Minh",
         "profile_fact", "general"),
        ("dup_023", "thích khách sạn gần biển",
         "Tôi thích khách sạn gần biển",
         "ưu tiên resort seaside", "Tôi ưu tiên resort seaside",
         "hotel_preference", "hotel"),
        ("dup_024", "ưu tiên ghế cửa sổ",
         "Tôi ưu tiên ghế cửa sổ",
         "muốn ngồi cạnh cửa sổ", "Tôi muốn ngồi cạnh cửa sổ",
         "flight_preference", "flight"),
        ("dup_025", "thường thuê xe 7 chỗ",
         "Tôi thường thuê xe 7 chỗ",
         "hay chọn xe bảy chỗ", "Tôi hay chọn xe bảy chỗ",
         "car_preference", "car"),
        ("dup_026", "thích lịch trình thoải mái",
         "Tôi thích lịch trình thoải mái",
         "ưu tiên pace chậm", "Tôi ưu tiên pace chậm",
         "general_preference", "general"),
        ("dup_027", "trả lời ngắn gọn",
         "Hãy nhớ trả lời ngắn gọn",
         "ưu tiên câu trả lời cô đọng", "Tôi ưu tiên câu trả lời cô đọng",
         "interaction_rule", "general"),
    ]
    for case_id, old_t, old_e, new_t, new_e, cat, dom in hard_dups:
        held.append(
            _case(
                case_id,
                split="test",
                requirement_id="REQ-TRANS-DUP",
                risk="paraphrase_duplicate",
                gold_action="noop",
                existing=[
                    _mem(
                        f"old-{case_id}",
                        memory_text=old_t,
                        category=cat,
                        domain=dom,
                        evidence_text=old_e,
                    )
                ],
                candidate=_cand(
                    memory_text=new_t, category=cat, domain=dom, evidence_text=new_e
                ),
                rationale="Paraphrase cùng ý → noop; exact-match có thể miss.",
                code_path=["calculate_transition", "_normalize_statement"],
            )
        )

    # --- CONFLICT: 7 easy polarity + 8 hard value-swap ---
    easy_conflicts = [
        ("conflict_013",
         "thích khách sạn gần trung tâm", "không thích khách sạn gần trung tâm",
         "Tôi thích khách sạn gần trung tâm",
         "Tôi không thích khách sạn gần trung tâm",
         "hotel_preference", "hotel"),
        ("conflict_014",
         "không thích quá cảnh dài", "ưu tiên quá cảnh dài",
         "Tôi không thích quá cảnh dài", "Tôi ưu tiên quá cảnh dài",
         "flight_preference", "flight"),
        ("conflict_015",
         "thích thuê xe có tài xế", "không thích thuê xe có tài xế",
         "Tôi thích thuê xe có tài xế", "Tôi không thích thuê xe có tài xế",
         "car_preference", "car"),
        ("conflict_019",
         "thích tour trekking", "không thích tour trekking",
         "Tôi thích tour trekking", "Tôi không thích tour trekking",
         "excursion_preference", "excursion"),
        ("conflict_020",
         "ưu tiên lịch trình thong thả", "không thích lịch trình thong thả",
         "Tôi ưu tiên lịch trình thong thả",
         "Tôi không thích lịch trình thong thả",
         "general_preference", "general"),
        ("conflict_021",
         "thích resort yên tĩnh", "không thích resort yên tĩnh",
         "Tôi thích resort yên tĩnh", "Tôi không thích resort yên tĩnh",
         "hotel_preference", "hotel"),
        ("conflict_022",
         "không thích bay đêm", "ưu tiên bay đêm",
         "Tôi không thích bay đêm", "Tôi ưu tiên bay đêm",
         "flight_preference", "flight"),
    ]
    for case_id, old_t, new_t, old_e, new_e, cat, dom in easy_conflicts:
        held.append(
            _case(
                case_id,
                split="test",
                requirement_id="REQ-TRANS-CONFLICT",
                risk="preference_conflict",
                gold_action="supersede",
                existing=[
                    _mem(
                        f"old-{case_id}",
                        memory_text=old_t,
                        category=cat,
                        domain=dom,
                        evidence_text=old_e,
                    )
                ],
                candidate=_cand(
                    memory_text=new_t, category=cat, domain=dom, evidence_text=new_e
                ),
                rationale="Polarity rõ thích↔không thích → supersede (lexical easy).",
                code_path=["calculate_transition", "_memories_conflict"],
            )
        )
    hard_conflicts = [
        ("conflict_016",
         "thích lịch trình thong thả", "Tôi thích lịch trình thong thả",
         "bây giờ muốn lịch trình dày đặc hơn",
         "Bây giờ tôi muốn lịch trình dày đặc hơn",
         "general_preference", "general"),
        ("conflict_017",
         "ưu tiên resort yên tĩnh", "Tôi ưu tiên resort yên tĩnh",
         "chuyển sang thích resort sôi động",
         "Tôi chuyển sang thích resort sôi động",
         "hotel_preference", "hotel"),
        ("conflict_018",
         "thích tour trekking", "Tôi thích tour trekking",
         "không còn hứng thú với tour trekking",
         "Tôi không còn hứng thú với tour trekking",
         "excursion_preference", "excursion"),
        ("conflict_023",
         "ưu tiên economy", "Tôi ưu tiên economy",
         "đổi sang business class", "Tôi đổi sang business class",
         "flight_preference", "flight"),
        ("conflict_024",
         "thích xe số tự động", "Tôi thích xe số tự động",
         "giờ muốn xe số sàn", "Giờ tôi muốn xe số sàn",
         "car_preference", "car"),
        ("conflict_025",
         "thích khách sạn boutique", "Tôi thích khách sạn boutique",
         "chuyển sang chuỗi lớn", "Tôi chuyển sang chuỗi lớn",
         "hotel_preference", "hotel"),
        ("conflict_026",
         "ưu tiên food tour", "Tôi ưu tiên food tour",
         "đổi sang museum tour", "Tôi đổi sang museum tour",
         "excursion_preference", "excursion"),
        ("conflict_027",
         "thích trả lời dài", "Tôi thích trả lời dài",
         "giờ muốn trả lời ngắn", "Giờ tôi muốn trả lời ngắn",
         "interaction_rule", "general"),
    ]
    for case_id, old_t, old_e, new_t, new_e, cat, dom in hard_conflicts:
        held.append(
            _case(
                case_id,
                split="test",
                requirement_id="REQ-TRANS-CONFLICT",
                risk="paraphrase_conflict",
                gold_action="supersede",
                existing=[
                    _mem(
                        f"old-{case_id}",
                        memory_text=old_t,
                        category=cat,
                        domain=dom,
                        evidence_text=old_e,
                    )
                ],
                candidate=_cand(
                    memory_text=new_t, category=cat, domain=dom, evidence_text=new_e
                ),
                rationale="Value-swap / soft conflict → supersede; polarity lexical có thể miss.",
                code_path=["calculate_transition", "_memories_conflict"],
            )
        )

    # --- CONDITION: 5 easy polarity + 5 hard value-swap ---
    easy_conditions = [
        ("condition_007",
         "ưu tiên economy khi đi du lịch", "không thích economy khi đi du lịch",
         "khi đi du lịch",
         "Tôi ưu tiên economy khi đi du lịch",
         "Tôi không thích economy khi đi du lịch",
         "flight_preference", "flight"),
        ("condition_008",
         "thích resort gần biển khi đi hè", "không thích resort gần biển khi đi hè",
         "khi đi hè",
         "Tôi thích resort gần biển khi đi hè",
         "Tôi không thích resort gần biển khi đi hè",
         "hotel_preference", "hotel"),
        ("condition_011",
         "thích xe 7 chỗ khi đi đông người",
         "không thích xe 7 chỗ khi đi đông người",
         "khi đi đông người",
         "Tôi thích xe 7 chỗ khi đi đông người",
         "Tôi không thích xe 7 chỗ khi đi đông người",
         "car_preference", "car"),
        ("condition_012",
         "ưu tiên tour trekking khi đi Đà Lạt",
         "không thích tour trekking khi đi Đà Lạt",
         "khi đi Đà Lạt",
         "Tôi ưu tiên tour trekking khi đi Đà Lạt",
         "Tôi không thích tour trekking khi đi Đà Lạt",
         "excursion_preference", "excursion"),
        ("condition_013",
         "thích lịch trình thong thả khi đi gia đình",
         "không thích lịch trình thong thả khi đi gia đình",
         "khi đi gia đình",
         "Tôi thích lịch trình thong thả khi đi gia đình",
         "Tôi không thích lịch trình thong thả khi đi gia đình",
         "general_preference", "general"),
    ]
    for case_id, old_t, new_t, cond, old_e, new_e, cat, dom in easy_conditions:
        held.append(
            _case(
                case_id,
                split="test",
                requirement_id="REQ-TRANS-CONDITION",
                risk="updated_condition",
                gold_action="supersede",
                existing=[
                    _mem(
                        f"old-{case_id}",
                        memory_text=old_t,
                        category=cat,
                        domain=dom,
                        evidence_text=old_e,
                        condition=cond,
                    )
                ],
                candidate=_cand(
                    memory_text=new_t,
                    category=cat,
                    domain=dom,
                    evidence_text=new_e,
                    condition=cond,
                ),
                rationale="Cùng condition, polarity đổi → supersede (lexical easy).",
                code_path=["calculate_transition", "_memories_conflict"],
            )
        )
    hard_conditions = [
        ("condition_009",
         "ưu tiên economy khi đi du lịch", "ưu tiên business khi đi du lịch",
         "khi đi du lịch", "khi đi du lịch",
         "Tôi ưu tiên economy khi đi du lịch",
         "Tôi ưu tiên business khi đi du lịch",
         "flight_preference", "flight",
         "Cùng condition, economy→business → supersede."),
        ("condition_010",
         "ưu tiên xe 7 chỗ khi đi đông người", "ưu tiên xe 4 chỗ khi đi đông người",
         "khi đi đông người", "khi đi đông người",
         "Tôi ưu tiên xe 7 chỗ khi đi đông người",
         "Tôi ưu tiên xe 4 chỗ khi đi đông người",
         "car_preference", "car",
         "Cùng condition, đổi kích thước xe → supersede."),
        ("condition_014",
         "ưu tiên boutique khi đi công tác", "ưu tiên chuỗi lớn khi đi công tác",
         "khi đi công tác", "khi đi công tác",
         "Tôi ưu tiên boutique khi đi công tác",
         "Tôi ưu tiên chuỗi lớn khi đi công tác",
         "hotel_preference", "hotel",
         "Cùng condition, boutique→chuỗi lớn → supersede."),
        ("condition_015",
         "ưu tiên food tour khi đi Đà Nẵng", "ưu tiên museum tour khi đi Đà Nẵng",
         "khi đi Đà Nẵng", "khi đi Đà Nẵng",
         "Tôi ưu tiên food tour khi đi Đà Nẵng",
         "Tôi ưu tiên museum tour khi đi Đà Nẵng",
         "excursion_preference", "excursion",
         "Cùng condition, food→museum tour → supersede."),
        ("condition_016",
         "ưu tiên pace chậm khi đi nghỉ", "ưu tiên pace nhanh khi đi nghỉ",
         "khi đi nghỉ", "khi đi nghỉ",
         "Tôi ưu tiên pace chậm khi đi nghỉ",
         "Tôi ưu tiên pace nhanh khi đi nghỉ",
         "general_preference", "general",
         "Cùng condition, pace chậm→nhanh → supersede."),
    ]
    for (
        case_id,
        old_t,
        new_t,
        old_cond,
        new_cond,
        old_e,
        new_e,
        cat,
        dom,
        rationale,
    ) in hard_conditions:
        held.append(
            _case(
                case_id,
                split="test",
                requirement_id="REQ-TRANS-CONDITION",
                risk="updated_condition_value_swap",
                gold_action="supersede",
                existing=[
                    _mem(
                        f"old-{case_id}",
                        memory_text=old_t,
                        category=cat,
                        domain=dom,
                        evidence_text=old_e,
                        condition=old_cond,
                    )
                ],
                candidate=_cand(
                    memory_text=new_t,
                    category=cat,
                    domain=dom,
                    evidence_text=new_e,
                    condition=new_cond,
                ),
                rationale=rationale,
                code_path=["calculate_transition", "_memories_conflict"],
            )
        )

    # --- SENSITIVE: 7 easy exact + 8 hard paraphrase ---
    easy_sensitive = [
        ("sensitive_011", "mật khẩu wifi nhà là homewifi",
         "Hãy nhớ mật khẩu wifi nhà là homewifi", "profile_fact", "general",
         "password_leak"),
        ("sensitive_012", "passport number B7654321",
         "My passport number B7654321", "profile_fact", "general",
         "passport_leak"),
        ("sensitive_013", "credit card 5500000000000004",
         "Remember credit card 5500000000000004", "profile_fact", "general",
         "card_leak"),
        ("sensitive_017", "mật khẩu tài khoản là secret99",
         "Hãy nhớ mật khẩu tài khoản là secret99", "profile_fact", "general",
         "password_leak"),
        ("sensitive_018", "số hộ chiếu của tôi là C1122334",
         "Hãy nhớ số hộ chiếu của tôi là C1122334", "profile_fact", "general",
         "passport_leak"),
        ("sensitive_019", "thẻ tín dụng của tôi là 4000000000000002",
         "Hãy nhớ thẻ tín dụng của tôi là 4000000000000002",
         "profile_fact", "general", "card_leak"),
        ("sensitive_020", "cvv của tôi là 456",
         "Hãy nhớ cvv của tôi là 456", "profile_fact", "general", "cvv_leak"),
    ]
    for case_id, text, evidence, cat, dom, risk in easy_sensitive:
        held.append(
            _case(
                case_id,
                split="test",
                requirement_id="REQ-TRANS-SENSITIVE",
                risk=risk,
                gold_action="reject",
                existing=[],
                candidate=_cand(
                    memory_text=text,
                    category=cat,
                    domain=dom,
                    evidence_text=evidence,
                    thread_id="t1",
                ),
                rationale="Exact sensitive token → reject (lexical easy).",
                code_path=["validate_memory_candidate"],
            )
        )
    hard_sensitive = [
        ("sensitive_014", "mã PIN thẻ của tôi là 1234",
         "Hãy nhớ mã PIN thẻ của tôi là 1234", "profile_fact", "general",
         "pin_leak"),
        ("sensitive_015", "OTP ngân hàng của tôi là 998877",
         "Hãy nhớ OTP ngân hàng của tôi là 998877", "profile_fact", "general",
         "otp_leak"),
        ("sensitive_016", "booking reference ABC123",
         "Tool vừa trả booking reference ABC123 với giá hiện tại",
         "flight_preference", "flight", "tool_paraphrase"),
        ("sensitive_021", "mã bảo mật thẻ ATM là 4321",
         "Hãy nhớ mã bảo mật thẻ ATM là 4321", "profile_fact", "general",
         "atm_pin_leak"),
        ("sensitive_022", "mã xác thực SMS là 556677",
         "Hãy nhớ mã xác thực SMS là 556677", "profile_fact", "general",
         "sms_otp_leak"),
        ("sensitive_023", "số CMND của tôi là 079123456789",
         "Hãy nhớ số CMND của tôi là 079123456789", "profile_fact", "general",
         "id_leak"),
        ("sensitive_024", "confirmation code XYZ987",
         "API trả confirmation code XYZ987 và giá hiện tại",
         "hotel_preference", "hotel", "tool_paraphrase"),
        ("sensitive_025", "mã PNR là QWERTY",
         "Hệ thống trả mã PNR là QWERTY", "flight_preference", "flight",
         "tool_paraphrase"),
    ]
    for case_id, text, evidence, cat, dom, risk in hard_sensitive:
        held.append(
            _case(
                case_id,
                split="test",
                requirement_id="REQ-TRANS-SENSITIVE",
                risk=risk,
                gold_action="reject",
                existing=[],
                candidate=_cand(
                    memory_text=text,
                    category=cat,
                    domain=dom,
                    evidence_text=evidence,
                    thread_id="t1",
                ),
                rationale="Credential/tool paraphrase → reject; exact token list có thể miss.",
                code_path=["validate_memory_candidate"],
            )
        )

    # --- AMBIGUOUS: 5 easy markers + 5 hard hedges outside marker list ---
    easy_ambiguous = [
        ("ambiguous_009", "thích khách sạn boutique",
         "Có thể tôi thích khách sạn boutique", "hotel_preference", "hotel"),
        ("ambiguous_010", "ưu tiên chuyến tối",
         "Perhaps tôi ưu tiên chuyến tối", "flight_preference", "flight"),
        ("ambiguous_013", "thích xe rộng rãi",
         "Maybe tôi thích xe rộng rãi", "car_preference", "car"),
        ("ambiguous_014", "thích tour ẩm thực",
         "Tôi chưa chắc có thích tour ẩm thực", "excursion_preference", "excursion"),
        ("ambiguous_015", "ưu tiên lịch thong thả",
         "Không chắc tôi ưu tiên lịch thong thả", "general_preference", "general"),
    ]
    for case_id, text, evidence, cat, dom in easy_ambiguous:
        held.append(
            _case(
                case_id,
                split="test",
                requirement_id="REQ-TRANS-AMBIGUOUS",
                risk="ambiguous",
                gold_action="reject",
                existing=[],
                candidate=_cand(
                    memory_text=text,
                    category=cat,
                    domain=dom,
                    evidence_text=evidence,
                    thread_id="t1",
                ),
                rationale="Exact ambiguous marker → reject (lexical easy).",
                code_path=["validate_memory_candidate", "_is_ambiguous"],
            )
        )
    hard_ambiguous = [
        ("ambiguous_011", "thích resort gần hồ",
         "Tôi nghĩ tôi thích resort gần hồ", "hotel_preference", "hotel"),
        ("ambiguous_012", "ưu tiên bay sáng",
         "Có vẻ tôi ưu tiên bay sáng", "flight_preference", "flight"),
        ("ambiguous_016", "thích xe hybrid",
         "Dường như tôi thích xe hybrid", "car_preference", "car"),
        ("ambiguous_017", "thích museum tour",
         "Khả năng là tôi thích museum tour", "excursion_preference", "excursion"),
        ("ambiguous_018", "ưu tiên trả lời ngắn",
         "E rằng tôi ưu tiên trả lời ngắn", "interaction_rule", "general"),
    ]
    for case_id, text, evidence, cat, dom in hard_ambiguous:
        held.append(
            _case(
                case_id,
                split="test",
                requirement_id="REQ-TRANS-AMBIGUOUS",
                risk="hedge_without_marker",
                gold_action="reject",
                existing=[],
                candidate=_cand(
                    memory_text=text,
                    category=cat,
                    domain=dom,
                    evidence_text=evidence,
                    thread_id="t1",
                ),
                rationale="Hedge ngoài list marker → reject; lexical có thể miss.",
                code_path=["validate_memory_candidate", "_is_ambiguous"],
            )
        )

    # --- INSERT: 20 valid new prefs (expect pass) ---
    inserts = [
        ("insert_018", "thích khách sạn có hồ bơi",
         "Tôi thích khách sạn có hồ bơi", "hotel_preference", "hotel",
         [_mem("exist-sea", memory_text="thích khách sạn gần biển",
               category="hotel_preference", domain="hotel",
               evidence_text="Tôi thích khách sạn gần biển")],
         "Aspect khác (hồ bơi vs gần biển) → insert."),
        ("insert_019", "muốn ghế cạnh lối đi",
         "Tôi muốn ghế cạnh lối đi", "flight_preference", "flight", [],
         "Preference ghế mới → insert."),
        ("insert_020", "thích xe hybrid",
         "Tôi thích xe hybrid", "car_preference", "car", [],
         "Preference xe mới → insert."),
        ("insert_021", "thích tour lặn biển",
         "Tôi thích tour lặn biển", "excursion_preference", "excursion", [],
         "Preference excursion mới → insert."),
        ("insert_022", "ưu tiên đi sớm hơn lịch",
         "Tôi ưu tiên đi sớm hơn lịch", "general_preference", "general", [],
         "Preference lịch trình mới → insert."),
        ("insert_023", "chị Lan",
         "Gọi tôi là chị Lan", "profile_fact", "general", [],
         "Profile fact mới → insert."),
        ("insert_024", "không thích hành lý ký gửi",
         "Tôi không thích hành lý ký gửi", "flight_preference", "flight", [],
         "Negative preference mới → insert."),
        ("insert_025", "thích homestay có sân vườn",
         "Tôi thích homestay có sân vườn", "hotel_preference", "hotel",
         [_mem("exist-flight", memory_text="ưu tiên bay thẳng",
               category="flight_preference", domain="flight",
               evidence_text="Tôi ưu tiên bay thẳng")],
         "Hotel mới, existing flight unrelated → insert."),
        ("insert_026", "trả lời bằng bullet ngắn",
         "Hãy nhớ trả lời bằng bullet ngắn", "interaction_rule", "general", [],
         "Interaction rule mới → insert."),
        ("insert_027", "thích khách sạn có gym",
         "Tôi thích khách sạn có gym", "hotel_preference", "hotel", [],
         "Hotel amenity mới → insert."),
        ("insert_028", "ưu tiên chuyến bay buổi sáng",
         "Tôi ưu tiên chuyến bay buổi sáng", "flight_preference", "flight", [],
         "Flight time preference mới → insert."),
        ("insert_029", "thường thuê xe điện",
         "Tôi thường thuê xe điện", "car_preference", "car", [],
         "Car preference mới → insert."),
        ("insert_030", "thích tour chụp ảnh",
         "Tôi thích tour chụp ảnh", "excursion_preference", "excursion", [],
         "Excursion preference mới → insert."),
        ("insert_031", "ưu tiên lịch trình linh hoạt",
         "Tôi ưu tiên lịch trình linh hoạt", "general_preference", "general", [],
         "General preference mới → insert."),
        ("insert_032", "anh Khoa",
         "Gọi tôi là anh Khoa", "profile_fact", "general", [],
         "Profile fact mới → insert."),
        ("insert_033", "không hỏi lại ngân sách",
         "Hãy nhớ không hỏi lại ngân sách", "interaction_rule", "general", [],
         "Interaction rule mới → insert."),
        ("insert_034", "thích resort có spa",
         "Tôi thích resort có spa", "hotel_preference", "hotel",
         [_mem("exist-car", memory_text="thích xe số tự động",
               category="car_preference", domain="car",
               evidence_text="Tôi thích xe số tự động")],
         "Hotel mới, existing car unrelated → insert."),
        ("insert_035", "ưu tiên ghế gần lối thoát hiểm",
         "Tôi ưu tiên ghế gần lối thoát hiểm", "flight_preference", "flight", [],
         "Flight seat preference mới → insert."),
        ("insert_036", "thích xe có cốp rộng",
         "Tôi thích xe có cốp rộng", "car_preference", "car", [],
         "Car preference mới → insert."),
        ("insert_037", "thường đi cùng bạn bè",
         "Tôi thường đi cùng bạn bè", "general_preference", "general", [],
         "Companion preference mới → insert."),
    ]
    for case_id, text, evidence, cat, dom, existing, rationale in inserts:
        held.append(
            _case(
                case_id,
                split="test",
                requirement_id="REQ-TRANS-INSERT",
                risk="false_noop",
                gold_action="insert",
                existing=existing,
                candidate=_cand(
                    memory_text=text,
                    category=cat,
                    domain=dom,
                    evidence_text=evidence,
                    thread_id="t1",
                ),
                rationale=rationale,
                code_path=["calculate_transition"],
            )
        )

    if len(held) != 85:
        raise ValueError(f"expected 85 held-out cases, got {len(held)}")
    return held


def write_dataset(cases: list[dict[str, Any]] | None = None) -> tuple[Path, Path]:
    rows = cases if cases is not None else build_cases()
    if len(rows) != 150:
        raise ValueError(f"expected 150 cases, got {len(rows)}")
    dev = sum(1 for r in rows if r["split"] == "development")
    test = sum(1 for r in rows if r["split"] == "test")
    if (dev, test) != (65, 85):
        raise ValueError(f"expected split 65/85, got {dev}/{test}")

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    jsonl_path = FIXTURE_DIR / "transition_cases.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    mapping = {row["case_id"]: row["split"] for row in rows}
    manifest = {
        "splits": {"development": dev, "test": test},
        "development_count": dev,
        "test_count": test,
        "total": len(rows),
        "note": (
            "test=held-out (85); mixes lexical-easy and policy-hard; "
            "development (65) is lexical for iteration"
        ),
        "by_requirement": {},
        "mapping": mapping,
    }
    by_req: dict[str, dict[str, int]] = {}
    for row in rows:
        req = row["requirement_id"]
        bucket = by_req.setdefault(req, {"development": 0, "test": 0, "total": 0})
        bucket[row["split"]] += 1
        bucket["total"] += 1
    manifest["by_requirement"] = by_req

    manifest_path = FIXTURE_DIR / "transition_split_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return jsonl_path, manifest_path


def main() -> int:
    jsonl_path, manifest_path = write_dataset()
    print(f"Wrote 150 cases to {jsonl_path}")
    print(f"Wrote manifest to {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
