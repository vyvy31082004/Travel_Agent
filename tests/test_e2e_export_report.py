from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from e2e_eval.human_export import build_review_markdown, export_review
from e2e_eval.report import build_summary, write_summary_report
from e2e_eval.schema import DEFAULT_FIXTURE_DIR, load_case


def test_human_export_builds_markdown(tmp_path: Path) -> None:
    case = load_case(DEFAULT_FIXTURE_DIR / "e2e_hotel_001.yaml")
    trace = {
        "metadata": {"case_id": case.id, "fixture_to_uuid": {"m_budget": "uuid-1"}},
        "final_answer": "Đề xuất khách sạn A",
        "tools": [],
        "global_recall": {},
        "domain_recall": {
            "hotel": {
                "applicability": {"m_budget": "apply", "m_quiet": "uncertain"},
                "applicability_reasons": {
                    "m_budget": "budget preference applies to hotel search",
                    "m_quiet": "quiet preference has no API field",
                },
                "applied_constraints": ["price_max=2000000"],
            }
        },
        "auto_scores": {},
    }
    text = build_review_markdown(case, trace)
    assert "Task Success" in text
    assert "Unanswerable" in text
    assert "Đề xuất khách sạn A" in text
    assert "m_budget" in text
    assert "budget preference applies" in text
    assert "price_max=2000000" in text
    assert "### Finalize" in text
    assert "Conversation summary (STM)" in text
    assert "(none)" in text


def test_human_export_includes_stm_summary() -> None:
    case = load_case(DEFAULT_FIXTURE_DIR / "e2e_summary_hotel_001.yaml")
    trace = {
        "metadata": {"case_id": case.id, "fixture_to_uuid": {"m_quiet": "uuid-1"}},
        "final_answer": "Khách sạn Đà Nẵng",
        "stm": {
            "summary": "Người dùng ở Đà Nẵng từ 10–12/10, 2 người.",
            "message_count": 2,
            "summarized_after_turn": 2,
        },
        "turns": [
            {
                "turn": 1,
                "user_message": "Tôi định ở Đà Nẵng.",
                "answer": "Bạn muốn ở ngày nào?",
                "summarize_forced": False,
                "scored": False,
            },
            {
                "turn": 2,
                "user_message": "Ở từ 10 đến 12/10, 2 người, ngân sách 1–2 triệu một đêm.",
                "answer": "Đã ghi nhận.",
                "summarize_forced": True,
                "scored": False,
            },
            {
                "turn": 3,
                "user_message": "Tìm khách sạn luôn đi.",
                "answer": "Khách sạn Đà Nẵng",
                "summarize_forced": False,
                "scored": True,
            },
        ],
        "tools": [],
        "global_recall": {},
        "domain_recall": {},
        "auto_scores": {},
    }
    text = build_review_markdown(case, trace)
    assert "Conversation summary (STM)" in text
    assert "Người dùng ở Đà Nẵng từ 10–12/10" in text
    assert "summarized_after_turn:** 2" in text
    assert "Conversation (one chat turn at a time)" in text
    assert "### Turn 1" in text
    assert "### Turn 2 (force summarize)" in text
    assert "### Turn 3 (scored)" in text
    assert "Tìm khách sạn luôn đi." in text
    assert "## Query" not in text


def test_export_review_writes_file(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(
        json.dumps(
            {
                "metadata": {"case_id": "e2e_hotel_001"},
                "final_answer": "ok",
                "tools": [],
                "global_recall": {},
                "domain_recall": {},
                "auto_scores": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    review = export_review(trace_path)
    assert review.exists()
    assert "E2E Review" in review.read_text(encoding="utf-8")


def test_report_summary_empty_runs(tmp_path: Path) -> None:
    summary = build_summary([])
    assert summary["run_count"] == 0
    json_path, md_path = write_summary_report(tmp_path, output_dir=tmp_path / "out")
    assert json_path.exists()
    assert md_path.exists()
