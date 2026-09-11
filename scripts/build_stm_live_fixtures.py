#!/usr/bin/env python3
"""Write curated STM live fixtures: 20 development + 30 test YAML cases + manifest.

Does not expand cyclic fillers — each case is a distinct Vietnamese scenario template.
Re-run to regenerate fixtures under tests/fixtures/short_term_memory_live/.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "fixtures" / "short_term_memory_live"
DEV = 20
TEST = 30

DESTINATIONS = [
    "Đà Nẵng",
    "Nha Trang",
    "Huế",
    "Hội An",
    "Phú Quốc",
    "Đà Lạt",
    "Sa Pa",
    "Hạ Long",
    "Cần Thơ",
    "Vũng Tàu",
]
ORIGINS = ["Hà Nội", "TP.HCM", "Đà Nẵng", "Hải Phòng"]


def _dump(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(
        payload,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    path.write_text(text, encoding="utf-8")


def _search_success_case(index: int, *, split: str, case_no: int) -> dict[str, Any]:
    dest = DESTINATIONS[index % len(DESTINATIONS)]
    day = 10 + (index % 15)
    check_in = f"2026-10-{day:02d}"
    check_out = f"2026-10-{day + 2:02d}"
    guests = 1 + (index % 3)
    budget = 1_500_000 + (index % 5) * 500_000
    kind = index % 4
    if kind == 0:
        return {
            "id": f"stm_live_success_hotel_{case_no:03d}",
            "split": split,
            "scenario": f"Search hotel {dest} với ngày/ngân sách",
            "metrics": ["success"],
            "messages": [
                f"Mình muốn khách sạn ở {dest}.",
                f"Check-in {day}/10/2026, check-out {day + 2}/10/2026, {guests} người, "
                f"ngân sách khoảng {budget // 1_000_000} triệu một đêm.",
                "Tìm khách sạn giúp mình.",
            ],
            # Guests often absent from hotel Result Store query; score search slots tools persist.
            "constraints": {
                "destination": dest,
                "check_in": check_in,
                "check_out": check_out,
            },
            "success_domain": "hotel",
        }
    if kind == 1:
        origin = ORIGINS[index % len(ORIGINS)]
        return {
            "id": f"stm_live_success_flight_{case_no:03d}",
            "split": split,
            "scenario": f"Search flight {origin} → {dest}",
            "metrics": ["success"],
            "messages": [
                f"Tìm vé máy bay từ {origin} đi {dest} ngày {day}/10/2026 cho {guests} người.",
            ],
            "constraints": {
                "origin": origin,
                "destination": dest,
                "date": check_in,
            },
            "success_domain": "flight",
        }
    if kind == 2:
        return {
            "id": f"stm_live_success_car_{case_no:03d}",
            "split": split,
            "scenario": f"Thuê xe đón sân bay về {dest}",
            "metrics": ["success"],
            "messages": [
                f"Cần thuê xe đón tại sân bay, trả tại {dest}, ngày {day}/10/2026, "
                f"{max(4, guests)} chỗ.",
            ],
            "constraints": {
                "dropoff": dest,
                "date": check_in,
            },
            "success_domain": "car",
        }
    return {
        "id": f"stm_live_success_change_{case_no:03d}",
        "split": split,
        "scenario": f"Đổi ý destination sang {dest} rồi search",
        "metrics": ["success"],
        "messages": [
            "Ban đầu mình nghĩ đi Nha Trang, check-in 12/10/2026, 2 người.",
            f"Thôi đổi sang {dest} giúp mình, vẫn 2 người, check-in {day}/10/2026 "
            f"check-out {day + 2}/10/2026.",
            "Tìm khách sạn theo lịch mới.",
        ],
        "constraints": {
            "destination": dest,
            "check_in": check_in,
            "check_out": check_out,
        },
        "success_domain": "hotel",
    }


def _reference_case(index: int, *, split: str, case_no: int) -> dict[str, Any]:
    kind = index % 5
    domain = ["hotel", "flight", "car", "excursion"][index % 4]
    req = f"req-{domain}-{case_no}"
    items = [f"{domain}_{i}" for i in range(1, 4)]
    if kind == 0:
        return {
            "id": f"stm_live_ref_ordinal_{case_no:03d}",
            "split": split,
            "scenario": f"Resolve ordinal position=2 trong {domain}",
            "metrics": ["reference"],
            "messages": ["Xin chào, mình đang xem kết quả tìm kiếm."],
            "reference": {
                "args": {"domain": domain, "position": 2},
                "gold": {"item_id": items[1]},
                "seed_visible_state": {
                    "visible_results": {
                        req: {
                            "domain": domain,
                            "search_id": f"s-{case_no}",
                            "displayed_item_ids": items,
                        }
                    },
                    "active_request_id": req,
                },
            },
        }
    if kind == 1:
        return {
            "id": f"stm_live_ref_first_{case_no:03d}",
            "split": split,
            "scenario": f"Resolve position=1 {domain}",
            "metrics": ["reference"],
            "messages": ["Cho mình xem lại danh sách kết quả vừa rồi."],
            "reference": {
                "args": {"position": 1},
                "gold": {"item_id": items[0]},
                "seed_visible_state": {
                    "visible_results": {
                        req: {
                            "domain": domain,
                            "search_id": f"s-{case_no}",
                            "displayed_item_ids": items,
                        }
                    },
                    "active_request_id": req,
                },
            },
        }
    if kind == 2:
        other = "flight" if domain != "flight" else "hotel"
        req2 = f"req-{other}-{case_no}"
        return {
            "id": f"stm_live_ref_ambiguous_{case_no:03d}",
            "split": split,
            "scenario": "Ambiguous multi-domain → clarification",
            "metrics": ["reference"],
            "messages": ["Mình muốn chọn cái đầu tiên."],
            "reference": {
                "args": {"position": 1},
                "gold": {"clarification": True},
                "seed_visible_state": {
                    "visible_results": {
                        req: {
                            "domain": domain,
                            "search_id": f"s-a-{case_no}",
                            "displayed_item_ids": items,
                        },
                        req2: {
                            "domain": other,
                            "search_id": f"s-b-{case_no}",
                            "displayed_item_ids": [f"{other}_1", f"{other}_2"],
                        },
                    }
                },
            },
        }
    if kind == 3:
        return {
            "id": f"stm_live_ref_oor_{case_no:03d}",
            "split": split,
            "scenario": "Out-of-range position → clarification",
            "metrics": ["reference"],
            "messages": ["Chọn giúp mình cái thứ 9 đi."],
            "reference": {
                "args": {"domain": domain, "position": 9},
                "gold": {"clarification": True},
                "seed_visible_state": {
                    "visible_results": {
                        req: {
                            "domain": domain,
                            "search_id": f"s-{case_no}",
                            "displayed_item_ids": items,
                        }
                    },
                    "active_request_id": req,
                },
            },
        }
    return {
        "id": f"stm_live_ref_itemid_{case_no:03d}",
        "split": split,
        "scenario": f"Resolve direct item_id {items[0]}",
        "metrics": ["reference"],
        "messages": [f"Chọn đúng mã {items[0]} giúp mình."],
        "reference": {
            "args": {"domain": domain, "item_id": items[0]},
            "gold": {"item_id": items[0]},
            "seed_visible_state": {
                "visible_results": {
                    req: {
                        "domain": domain,
                        "search_id": f"s-{case_no}",
                        "displayed_item_ids": items,
                    }
                },
                "active_request_id": req,
            },
        },
    }


def _factual_case(index: int, *, split: str, case_no: int) -> dict[str, Any]:
    dest = DESTINATIONS[index % len(DESTINATIONS)]
    day = 10 + (index % 12)
    facts = [
        (
            f"Ngân sách khách sạn ở {dest} dưới 2 triệu một đêm, 2 người, "
            f"ở từ {day}/10 đến {day + 2}/10/2026.",
            "Ngân sách khách sạn là bao nhiêu?",
            "duoi 2 trieu",
            "đầu",
        ),
        (
            f"Mình không muốn transit quá 3 giờ khi bay tới {dest} ngày {day}/10/2026.",
            "Giới hạn transit là bao nhiêu giờ?",
            "3 gio",
            "giữa",
        ),
        (
            f"Tour ở {dest} ngày {day}/10/2026 khoảng 4 tiếng, 2 người lớn.",
            "Tour kéo dài bao lâu?",
            "4 tieng",
            "cuối",
        ),
        (
            f"Thuê xe đón sân bay về {dest} ngày {day}/10/2026, cần ghế trẻ em.",
            "Có cần ghế trẻ em không?",
            "ghe tre em",
            "giữa",
        ),
    ]
    setup, probe, gold, position = facts[index % len(facts)]
    return {
        "id": f"stm_live_factual_{case_no:03d}",
        "split": split,
        "scenario": f"Factual recall after summary ({position})",
        "metrics": ["factual_recall"],
        "force_summarize_penultimate": True,
        "messages": [
            setup,
            "Ok mình ghi nhận vậy, chưa cần tìm ngay.",
            "Tóm lại giúp mình các ràng buộc vừa nói.",
        ],
        "probe": probe,
        "gold_answer": gold,
        "position": position,
        "phase": "after",
    }


def _success_only_case(index: int, *, split: str, case_no: int) -> dict[str, Any]:
    dest = DESTINATIONS[index % len(DESTINATIONS)]
    day = 14 + (index % 10)
    check_in = f"2026-11-{day:02d}"
    check_out = f"2026-11-{day + 2:02d}"
    guests = 2 + (index % 2)
    return {
        "id": f"stm_live_success_{case_no:03d}",
        "split": split,
        "scenario": f"Task success search hotel {dest}",
        "metrics": ["success"],
        "messages": [
            f"Tìm khách sạn {dest}, check-in {day}/11/2026, ở 2 đêm, {guests} người, "
            "ngân sách dưới 3 triệu.",
        ],
        "constraints": {
            "destination": dest,
            "check_in": check_in,
            "check_out": check_out,
        },
        "success_domain": "hotel",
    }


def build_all_cases() -> list[dict[str, Any]]:
    """20 development + 30 test with reference / factual_recall / success coverage."""
    cases: list[dict[str, Any]] = []
    # Development: 5 search-success + 5 reference + 5 factual + 5 success-only (20)
    for i in range(5):
        cases.append(_search_success_case(i, split="development", case_no=i + 1))
    for i in range(5):
        cases.append(_reference_case(i, split="development", case_no=i + 1))
    for i in range(5):
        cases.append(_factual_case(i, split="development", case_no=i + 1))
    for i in range(5):
        cases.append(_success_only_case(i, split="development", case_no=i + 1))

    # Test: 10 search-success + 10 reference + 5 factual + 5 success-only = 30
    for i in range(10):
        cases.append(_search_success_case(i + 5, split="test", case_no=100 + i + 1))
    for i in range(10):
        cases.append(_reference_case(i + 5, split="test", case_no=100 + i + 1))
    for i in range(5):
        cases.append(_factual_case(i + 5, split="test", case_no=100 + i + 1))
    for i in range(5):
        cases.append(_success_only_case(i + 5, split="test", case_no=100 + i + 1))

    assert len(cases) == DEV + TEST, len(cases)
    assert sum(1 for c in cases if c["split"] == "development") == DEV
    assert sum(1 for c in cases if c["split"] == "test") == TEST
    return cases


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("stm_live_*.yaml"):
        old.unlink()
    cases = build_all_cases()
    manifest_cases = []
    for case in cases:
        filename = f"{case['id']}.yaml"
        _dump(OUT / filename, case)
        tags = list(case["metrics"])
        tags.append(case["split"])
        manifest_cases.append({"id": case["id"], "file": filename, "tags": tags})
    manifest = {
        "suite": "stm-live",
        "development": DEV,
        "test": TEST,
        "cases": manifest_cases,
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(cases)} cases to {OUT}")


if __name__ == "__main__":
    main()
