#!/usr/bin/env python3
"""Build short-term memory eval fixtures: 65 development + 85 held-out per suite."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "fixtures" / "short_term_memory_eval"
DEV = 65
TEST = 85
TOTAL = DEV + TEST

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
ORIGINS = ["Hà Nội", "TP.HCM", "Đà Nẵng", "Hải Phòng", "Cần Thơ"]
DOMAINS = ["hotel", "flight", "car", "excursion"]
POSITIONS = ["đầu", "giữa", "cuối"]
PHASES = ["before", "after"]

FACTS = [
    ("Giới hạn transit là bao nhiêu giờ?", "transit khong qua 3 gio", "toi muon transit khong qua 3 gio"),
    ("Ngân sách khách sạn là bao nhiêu?", "duoi 2 trieu", "ngan sach duoi 2 trieu"),
    ("Số khách là mấy người?", "2 nguoi", "co 2 nguoi lon"),
    ("Ngày đi là ngày nào?", "ngay 15 thang 9", "ngay 15 thang 9 nam 2026"),
    ("Có yêu cầu phòng không hút thuốc không?", "co phong khong hut thuoc", "co yeu cau phong khong hut thuoc"),
    ("Muốn ghế cửa sổ không?", "co muon ghe cua so", "toi co muon ghe cua so"),
    ("Pickup ở đâu?", "san bay", "don tai san bay"),
    ("Tour mấy tiếng?", "4 tieng", "tour keo dai 4 tieng"),
    ("Hạng sao tối thiểu?", "tu 4 sao", "toi thieu tu 4 sao"),
    ("Có cần ghế trẻ em không?", "can ghe tre em", "co can ghe tre em"),
]


def _split_for(index: int) -> str:
    return "development" if index < DEV else "test"


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_state_cases() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i in range(TOTAL):
        split = _split_for(i)
        dest = DESTINATIONS[i % len(DESTINATIONS)]
        domain = DOMAINS[i % len(DOMAINS)]
        day = 10 + (i % 18)
        guests = 1 + (i % 4)
        budget = 1_500_000 + (i % 10) * 250_000
        check_in = f"2026-09-{day:02d}"
        check_out = f"2026-09-{day + 2:02d}"
        req_id = f"req-{domain}-{i + 1}"
        kind = i % 6

        if kind == 0:
            # Full match
            params = {
                "destination": dest,
                "check_in": check_in,
                "check_out": check_out,
                "guests": guests,
                "budget": budget,
            }
            if domain == "flight":
                params = {
                    "origin": ORIGINS[i % len(ORIGINS)],
                    "destination": dest,
                    "date": check_in,
                    "guests": guests,
                }
            elif domain == "car":
                params = {
                    "pickup": "sân bay",
                    "dropoff": dest,
                    "date": check_in,
                    "seats": max(4, guests),
                }
            elif domain == "excursion":
                params = {"destination": dest, "date": check_in, "guests": guests}
            gold = {f"{domain}.{k}": v for k, v in params.items()}
            gold["active_request_id"] = req_id
            rows.append(
                {
                    "case_id": f"state_full_{i + 1:03d}",
                    "split": split,
                    "state": {
                        "requests": {domain: params},
                        "active_request_id": req_id,
                    },
                    "gold": gold,
                }
            )
        elif kind == 1:
            # One slot wrong (guests)
            params = {
                "destination": dest,
                "check_in": check_in,
                "guests": guests + 1,
                "budget": budget,
            }
            gold = {
                f"{domain}.destination": dest,
                f"{domain}.check_in": check_in,
                f"{domain}.guests": guests,
                f"{domain}.budget": budget,
                "active_request_id": req_id,
            }
            if domain != "hotel":
                # keep hotel-like slots only for hotel; for others use destination+guests
                params = {"destination": dest, "guests": guests + 1}
                gold = {
                    f"{domain}.destination": dest,
                    f"{domain}.guests": guests,
                    "active_request_id": req_id,
                }
            rows.append(
                {
                    "case_id": f"state_one_slot_wrong_{i + 1:03d}",
                    "split": split,
                    "state": {
                        "requests": {domain: params},
                        "active_request_id": req_id,
                    },
                    "gold": gold,
                }
            )
        elif kind == 2:
            # Normalized date (DD/MM/YYYY in state)
            date_iso = check_in
            date_vn = f"{day:02d}/09/2026"
            params = {"destination": dest, "check_in": date_vn, "guests": guests}
            rows.append(
                {
                    "case_id": f"state_normalized_date_{i + 1:03d}",
                    "split": split,
                    "state": {
                        "requests": {domain: params},
                        "active_request_id": req_id,
                    },
                    "gold": {
                        f"{domain}.destination": dest,
                        f"{domain}.check_in": date_iso,
                        f"{domain}.guests": guests,
                        "active_request_id": req_id,
                    },
                }
            )
        elif kind == 3:
            # Selected item
            item_id = f"{domain}_{(i % 5) + 1}"
            params = {"destination": dest, "date": check_in}
            if domain == "flight":
                params = {
                    "origin": ORIGINS[i % len(ORIGINS)],
                    "destination": dest,
                    "date": check_in,
                }
            rows.append(
                {
                    "case_id": f"state_selected_item_{i + 1:03d}",
                    "split": split,
                    "state": {
                        "requests": {domain: params},
                        "selected_items": {domain: {"item_id": item_id}},
                        "active_request_id": req_id,
                    },
                    "gold": {
                        **{f"{domain}.{k}": v for k, v in params.items()},
                        f"{domain}.selected": item_id,
                        "active_request_id": req_id,
                    },
                }
            )
        elif kind == 4:
            # Extra non-gold slot (false positive)
            params = {"destination": dest, "guests": guests, "pets": True}
            rows.append(
                {
                    "case_id": f"state_extra_slot_{i + 1:03d}",
                    "split": split,
                    "state": {
                        "requests": {domain: params},
                        "active_request_id": req_id,
                    },
                    "gold": {
                        f"{domain}.destination": dest,
                        f"{domain}.guests": guests,
                        "active_request_id": req_id,
                    },
                }
            )
        else:
            # Budget as formatted string vs int
            params = {
                "destination": dest,
                "budget": f"{budget:,}".replace(",", "."),
                "guests": guests,
            }
            rows.append(
                {
                    "case_id": f"state_budget_norm_{i + 1:03d}",
                    "split": split,
                    "state": {
                        "requests": {domain: params},
                        "active_request_id": req_id,
                    },
                    "gold": {
                        f"{domain}.destination": dest,
                        f"{domain}.budget": budget,
                        f"{domain}.guests": guests,
                        "active_request_id": req_id,
                    },
                }
            )
    # Preserve classic seed ids used by unit tests (overwrite first matching kinds)
    seed_overrides = {
        "state_full_001": rows[0],
        "state_one_slot_wrong_001": next(
            r for r in rows if r["case_id"].startswith("state_one_slot_wrong_")
        ),
        "state_normalized_date_001": next(
            r for r in rows if r["case_id"].startswith("state_normalized_date_")
        ),
        "state_selected_item_001": next(
            r for r in rows if r["case_id"].startswith("state_selected_item_")
        ),
        "state_extra_slot_001": next(
            r for r in rows if r["case_id"].startswith("state_extra_slot_")
        ),
    }
    # Rewrite first five development cases to classic seeds with known content
    rows[0] = {
        "case_id": "state_full_001",
        "split": "development",
        "state": {
            "requests": {
                "hotel": {
                    "destination": "Đà Nẵng",
                    "check_in": "2026-09-15",
                    "check_out": "2026-09-17",
                    "guests": 2,
                    "budget": 2000000,
                }
            },
            "active_request_id": "req-hotel-1",
        },
        "gold": {
            "hotel.destination": "Đà Nẵng",
            "hotel.check_in": "2026-09-15",
            "hotel.check_out": "2026-09-17",
            "hotel.guests": 2,
            "hotel.budget": 2000000,
            "active_request_id": "req-hotel-1",
        },
    }
    rows[1] = {
        "case_id": "state_one_slot_wrong_001",
        "split": "development",
        "state": {
            "requests": {
                "hotel": {
                    "destination": "Đà Nẵng",
                    "check_in": "2026-09-15",
                    "check_out": "2026-09-17",
                    "guests": 3,
                    "budget": 2000000,
                }
            },
            "active_request_id": "req-hotel-1",
        },
        "gold": {
            "hotel.destination": "Đà Nẵng",
            "hotel.check_in": "2026-09-15",
            "hotel.check_out": "2026-09-17",
            "hotel.guests": 2,
            "hotel.budget": 2000000,
            "active_request_id": "req-hotel-1",
        },
    }
    rows[2] = {
        "case_id": "state_normalized_date_001",
        "split": "development",
        "state": {
            "requests": {
                "hotel": {
                    "destination": "Nha Trang",
                    "check_in": "15/09/2026",
                    "guests": 2,
                }
            },
            "active_request_id": "req-hotel-2",
        },
        "gold": {
            "hotel.destination": "Nha Trang",
            "hotel.check_in": "2026-09-15",
            "hotel.guests": 2,
            "active_request_id": "req-hotel-2",
        },
    }
    # Keep selected/extra seeds in test split positions 65+
    rows[DEV] = {
        "case_id": "state_selected_item_001",
        "split": "test",
        "state": {
            "requests": {
                "flight": {
                    "origin": "Hà Nội",
                    "destination": "Đà Nẵng",
                    "date": "2026-09-15",
                }
            },
            "selected_items": {"flight": {"item_id": "flight_2"}},
            "active_request_id": "req-flight-1",
        },
        "gold": {
            "flight.origin": "Hà Nội",
            "flight.destination": "Đà Nẵng",
            "flight.date": "2026-09-15",
            "flight.selected": "flight_2",
            "active_request_id": "req-flight-1",
        },
    }
    rows[DEV + 1] = {
        "case_id": "state_extra_slot_001",
        "split": "test",
        "state": {
            "requests": {"hotel": {"destination": "Huế", "guests": 2, "pets": True}},
            "active_request_id": "req-hotel-3",
        },
        "gold": {
            "hotel.destination": "Huế",
            "hotel.guests": 2,
            "active_request_id": "req-hotel-3",
        },
    }
    del seed_overrides  # silence unused after rewrite
    return rows


def build_reference_cases() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i in range(TOTAL):
        split = _split_for(i)
        domain = DOMAINS[i % len(DOMAINS)]
        n_items = 2 + (i % 4)
        items = [f"{domain}_{j + 1}" for j in range(n_items)]
        req_id = f"req-{domain}-{i + 1}"
        kind = i % 5

        if kind == 0:
            position = 1 + (i % n_items)
            rows.append(
                {
                    "case_id": f"ref_ordinal_{i + 1:03d}",
                    "split": split,
                    "args": {"domain": domain, "position": position},
                    "state": {
                        "visible_results": {
                            req_id: {
                                "domain": domain,
                                "search_id": f"s-{i + 1}",
                                "displayed_item_ids": items,
                            }
                        },
                        "active_request_id": req_id,
                    },
                    "gold": {"item_id": items[position - 1]},
                }
            )
        elif kind == 1:
            rows.append(
                {
                    "case_id": f"ref_first_{i + 1:03d}",
                    "split": split,
                    "args": {"position": 1},
                    "state": {
                        "visible_results": {
                            req_id: {
                                "domain": domain,
                                "search_id": f"s-{i + 1}",
                                "displayed_item_ids": items,
                            }
                        },
                        "active_request_id": req_id,
                    },
                    "gold": {"item_id": items[0]},
                }
            )
        elif kind == 2:
            other = DOMAINS[(i + 1) % len(DOMAINS)]
            rows.append(
                {
                    "case_id": f"ref_ambiguous_{i + 1:03d}",
                    "split": split,
                    "args": {"position": 1},
                    "state": {
                        "visible_results": {
                            f"req-{domain}-a": {
                                "domain": domain,
                                "search_id": "s-a",
                                "displayed_item_ids": items,
                            },
                            f"req-{other}-b": {
                                "domain": other,
                                "search_id": "s-b",
                                "displayed_item_ids": [
                                    f"{other}_1",
                                    f"{other}_2",
                                ],
                            },
                        }
                    },
                    "gold": {"clarification": True},
                }
            )
        elif kind == 3:
            rows.append(
                {
                    "case_id": f"ref_out_of_range_{i + 1:03d}",
                    "split": split,
                    "args": {"domain": domain, "position": n_items + 3},
                    "state": {
                        "visible_results": {
                            req_id: {
                                "domain": domain,
                                "search_id": f"s-{i + 1}",
                                "displayed_item_ids": items,
                            }
                        },
                        "active_request_id": req_id,
                    },
                    "gold": {"clarification": True},
                }
            )
        else:
            # Direct item_id resolve
            rows.append(
                {
                    "case_id": f"ref_item_id_{i + 1:03d}",
                    "split": split,
                    "args": {"domain": domain, "item_id": items[0]},
                    "state": {
                        "visible_results": {
                            req_id: {
                                "domain": domain,
                                "search_id": f"s-{i + 1}",
                                "displayed_item_ids": items,
                            }
                        },
                        "active_request_id": req_id,
                    },
                    "gold": {"item_id": items[0]},
                }
            )

    rows[0] = {
        "case_id": "ref_ordinal_001",
        "split": "development",
        "args": {"domain": "hotel", "position": 2},
        "state": {
            "visible_results": {
                "req-hotel-1": {
                    "domain": "hotel",
                    "search_id": "s-1",
                    "displayed_item_ids": ["hotel_1", "hotel_2", "hotel_3"],
                }
            },
            "active_request_id": "req-hotel-1",
        },
        "gold": {"item_id": "hotel_2"},
    }
    rows[1] = {
        "case_id": "ref_first_001",
        "split": "development",
        "args": {"position": 1},
        "state": {
            "visible_results": {
                "req-flight-1": {
                    "domain": "flight",
                    "search_id": "s-2",
                    "displayed_item_ids": ["flight_1", "flight_2"],
                }
            },
            "active_request_id": "req-flight-1",
        },
        "gold": {"item_id": "flight_1"},
    }
    rows[2] = {
        "case_id": "ref_ambiguous_001",
        "split": "development",
        "args": {"position": 1},
        "state": {
            "visible_results": {
                "req-hotel-1": {
                    "domain": "hotel",
                    "search_id": "s-1",
                    "displayed_item_ids": ["hotel_1", "hotel_2"],
                },
                "req-flight-1": {
                    "domain": "flight",
                    "search_id": "s-2",
                    "displayed_item_ids": ["flight_1", "flight_2"],
                },
            }
        },
        "gold": {"clarification": True},
    }
    rows[DEV] = {
        "case_id": "ref_out_of_range_001",
        "split": "test",
        "args": {"domain": "hotel", "position": 5},
        "state": {
            "visible_results": {
                "req-hotel-1": {
                    "domain": "hotel",
                    "search_id": "s-1",
                    "displayed_item_ids": ["hotel_1", "hotel_2"],
                }
            },
            "active_request_id": "req-hotel-1",
        },
        "gold": {"clarification": True},
    }
    rows[DEV + 1] = {
        "case_id": "ref_wrong_item_expected_001",
        "split": "test",
        "args": {"domain": "hotel", "position": 1},
        "state": {
            "visible_results": {
                "req-hotel-1": {
                    "domain": "hotel",
                    "search_id": "s-1",
                    "displayed_item_ids": ["hotel_1", "hotel_2"],
                }
            },
            "active_request_id": "req-hotel-1",
        },
        "gold": {"item_id": "hotel_1"},
    }
    return rows


def build_factual_recall_cases() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i in range(TOTAL):
        split = _split_for(i)
        position = POSITIONS[i % len(POSITIONS)]
        phase = PHASES[i % len(PHASES)]
        probe, gold, paraphrase = FACTS[i % len(FACTS)]
        kind = i % 4
        if kind == 0:
            predicted = paraphrase
            case_id = f"recall_ok_para_{i + 1:03d}"
        elif kind == 1:
            predicted = gold
            case_id = f"recall_ok_exact_{i + 1:03d}"
        elif kind == 2:
            predicted = "toi khong nho"
            case_id = f"recall_lost_{i + 1:03d}"
        else:
            # Partial cover that still matches token coverage when paraphrase shares tokens
            predicted = paraphrase
            case_id = f"recall_ok_cover_{i + 1:03d}"
        rows.append(
            {
                "case_id": case_id,
                "split": split,
                "position": position,
                "phase": phase,
                "probe": probe,
                "predicted_answer": predicted,
                "gold_answer": gold,
            }
        )

    rows[0] = {
        "case_id": "recall_head_before_001",
        "split": "development",
        "position": "đầu",
        "phase": "before",
        "probe": "Giới hạn transit là bao nhiêu giờ?",
        "predicted_answer": "toi khong muon transit qua 3 gio",
        "gold_answer": "transit khong qua 3 gio",
    }
    rows[1] = {
        "case_id": "recall_head_after_001",
        "split": "development",
        "position": "đầu",
        "phase": "after",
        "probe": "Giới hạn transit là bao nhiêu giờ?",
        "predicted_answer": "toi muon transit khong qua 3 gio",
        "gold_answer": "transit khong qua 3 gio",
    }
    rows[2] = {
        "case_id": "recall_mid_after_001",
        "split": "development",
        "position": "giữa",
        "phase": "after",
        "probe": "Ngân sách khách sạn là bao nhiêu?",
        "predicted_answer": "duoi 2 trieu",
        "gold_answer": "duoi 2 trieu",
    }
    rows[DEV] = {
        "case_id": "recall_tail_after_001",
        "split": "test",
        "position": "cuối",
        "phase": "after",
        "probe": "Số khách là mấy người?",
        "predicted_answer": "2 nguoi",
        "gold_answer": "2 nguoi",
    }
    rows[DEV + 1] = {
        "case_id": "recall_mid_lost_001",
        "split": "test",
        "position": "giữa",
        "phase": "after",
        "probe": "Ngày đi là ngày nào?",
        "predicted_answer": "toi khong nho",
        "gold_answer": "ngay 15 thang 9",
    }
    rows[DEV + 2] = {
        "case_id": "recall_head_after_002",
        "split": "test",
        "position": "đầu",
        "phase": "after",
        "probe": "Có yêu cầu phòng không hút thuốc không?",
        "predicted_answer": "co, phong khong hut thuoc",
        "gold_answer": "co phong khong hut thuoc",
    }
    return rows


def build_success_cases() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i in range(TOTAL):
        split = _split_for(i)
        domain = DOMAINS[i % len(DOMAINS)]
        item = f"{domain}_{(i % 5) + 1}"
        day = 10 + (i % 18)
        date = f"2026-09-{day:02d}"
        guests = 1 + (i % 4)
        kind = i % 4
        if kind == 0:
            rows.append(
                {
                    "case_id": f"success_full_{i + 1:03d}",
                    "split": split,
                    "scenario": f"Tìm {domain} tại {DESTINATIONS[i % len(DESTINATIONS)]}, chọn và xác nhận",
                    "final_action": {
                        "selected_item": item,
                        "check_in": date,
                        "guests": guests,
                    },
                    "constraints": {
                        "selected_item": item,
                        "check_in": date,
                        "guests": guests,
                    },
                }
            )
        elif kind == 1:
            new_date = f"2026-09-{day + 1:02d}"
            rows.append(
                {
                    "case_id": f"success_change_mind_{i + 1:03d}",
                    "split": split,
                    "scenario": f"Đổi ngày từ {date} sang {new_date} rồi đặt",
                    "final_action": {"selected_item": item, "date": new_date},
                    "constraints": {"selected_item": item, "date": new_date},
                }
            )
        elif kind == 2:
            new_date = f"2026-09-{day + 1:02d}"
            rows.append(
                {
                    "case_id": f"success_violation_{i + 1:03d}",
                    "split": split,
                    "scenario": "Đặt nhưng dùng ngày cũ sau khi user đã đổi ý",
                    "final_action": {"selected_item": item, "date": date},
                    "constraints": {"selected_item": item, "date": new_date},
                }
            )
        else:
            rows.append(
                {
                    "case_id": f"success_car_like_{i + 1:03d}",
                    "split": split,
                    "scenario": "Đặt xe/tour đúng ràng buộc",
                    "final_action": {
                        "selected_item": item,
                        "pickup": "sân bay",
                        "seats": 4,
                    },
                    "constraints": {
                        "selected_item": item,
                        "pickup": "sân bay",
                        "seats": 4,
                    },
                }
            )

    rows[0] = {
        "case_id": "success_full_001",
        "split": "development",
        "scenario": "Tìm khách sạn Đà Nẵng, chọn khách sạn thứ 2, đổi ngày ở, xác nhận",
        "final_action": {
            "selected_item": "hotel_2",
            "check_in": "2026-09-16",
            "guests": 2,
        },
        "constraints": {
            "selected_item": "hotel_2",
            "check_in": "2026-09-16",
            "guests": 2,
        },
    }
    rows[1] = {
        "case_id": "success_change_mind_001",
        "split": "development",
        "scenario": "Đổi ngày từ 15 sang 16 rồi đặt",
        "final_action": {"selected_item": "flight_1", "date": "2026-09-16"},
        "constraints": {"selected_item": "flight_1", "date": "2026-09-16"},
    }
    rows[DEV] = {
        "case_id": "success_violation_001",
        "split": "test",
        "scenario": "Đặt nhưng dùng ngày cũ sau khi user đã đổi ý",
        "final_action": {"selected_item": "flight_1", "date": "2026-09-15"},
        "constraints": {"selected_item": "flight_1", "date": "2026-09-16"},
    }
    rows[DEV + 1] = {
        "case_id": "success_full_002",
        "split": "test",
        "scenario": "Đặt xe đưa đón đúng ràng buộc",
        "final_action": {
            "selected_item": "car_1",
            "pickup": "sân bay",
            "seats": 4,
        },
        "constraints": {
            "selected_item": "car_1",
            "pickup": "sân bay",
            "seats": 4,
        },
    }
    return rows


def main() -> None:
    suites = {
        "state_cases.jsonl": build_state_cases(),
        "reference_cases.jsonl": build_reference_cases(),
        "factual_recall_cases.jsonl": build_factual_recall_cases(),
        "success_cases.jsonl": build_success_cases(),
    }
    for name, rows in suites.items():
        assert len(rows) == TOTAL, f"{name} expected {TOTAL}, got {len(rows)}"
        dev = sum(1 for r in rows if r["split"] == "development")
        test = sum(1 for r in rows if r["split"] == "test")
        assert dev == DEV and test == TEST, f"{name} split {dev}/{test}"
        ids = [r["case_id"] for r in rows]
        assert len(ids) == len(set(ids)), f"{name} duplicate case_id"
        _write_jsonl(OUT / name, rows)
        print(f"Wrote {OUT / name}: {dev} development + {test} test")


if __name__ == "__main__":
    main()
