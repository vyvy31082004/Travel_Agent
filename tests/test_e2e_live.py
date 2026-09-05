"""
Live E2E tests for domain memory cases.

Run manually when API keys, MCP servers, and Postgres are available:

  pytest tests/test_e2e_live.py -m "live and e2e" -s -v
  pytest tests/test_e2e_live.py -m "live and e2e" -k multi -s -v
"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from e2e_eval.asyncio_compat import run_async
from e2e_eval.runner import run_case
from e2e_eval.schema import DEFAULT_FIXTURE_DIR, load_case
from planner_smoke_lib import has_llm_api_key


MCP_SERVER_PORTS = (8001, 8002, 8003, 8004)
REPORTS_DIR = PROJECT_ROOT / "src" / "reports" / "e2e_runs"

SINGLE_DOMAIN_CASES = [
    "e2e_hotel_001",
    "e2e_flight_001",
    "e2e_car_001",
    "e2e_excursion_001",
    "e2e_override_hotel_001",
    "e2e_override_flight_001",
    "e2e_override_car_001",
    "e2e_override_excursion_001",
    "e2e_summary_hotel_001",
    "e2e_summary_flight_001",
    "e2e_summary_car_001",
    "e2e_summary_excursion_001",
    "e2e_write_hotel_001",
    "e2e_write_car_insert_001",
    "e2e_write_excursion_supersede_001",
    "e2e_write_global_name_001",
    "e2e_global_profile_name_001",
]

MULTI_DOMAIN_CASES = [
    "e2e_multi_hotel_flight_001",
    "e2e_multi_flight_car_001",
    "e2e_multi_car_excursion_001",
    "e2e_multi_excursion_hotel_001",
]


def mcp_servers_available(timeout: float = 0.5) -> bool:
    for port in MCP_SERVER_PORTS:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=timeout):
                pass
        except OSError:
            return False
    return True


def e2e_stack_ready() -> bool:
    return bool(os.getenv("DATABASE_URL")) and has_llm_api_key() and mcp_servers_available()


@pytest.mark.live
@pytest.mark.e2e
@pytest.mark.skipif(not e2e_stack_ready(), reason="Requires DATABASE_URL, LLM API key, MCP 8001-8004")
@pytest.mark.parametrize("case_id", SINGLE_DOMAIN_CASES)
def test_e2e_single_domain_case_runs_and_passes_auto(case_id: str) -> None:
    case = load_case(DEFAULT_FIXTURE_DIR / f"{case_id}.yaml")
    result = run_async(
        run_case(
            case,
            reports_dir=REPORTS_DIR,
            verbose=True,
        )
    )
    assert result.trace_path.exists()
    assert result.trace.get("final_answer")
    integrity = (result.auto_scores.get("trace_integrity") or {}).get("status")
    answer_preview = (result.trace.get("final_answer") or "")[:500]
    print(f"\n[{case_id}] trace_integrity={integrity}")
    print(answer_preview.encode("ascii", errors="backslashreplace").decode("ascii"))
    assert integrity == "PASS", f"[{case_id}] auto_scores={result.auto_scores}"


@pytest.mark.live
@pytest.mark.e2e
@pytest.mark.multi
@pytest.mark.skipif(not e2e_stack_ready(), reason="Requires DATABASE_URL, LLM API key, MCP 8001-8004")
@pytest.mark.parametrize("case_id", MULTI_DOMAIN_CASES)
def test_e2e_multi_domain_case_runs_and_passes_auto(case_id: str) -> None:
    case = load_case(DEFAULT_FIXTURE_DIR / f"{case_id}.yaml")
    result = run_async(
        run_case(
            case,
            reports_dir=REPORTS_DIR,
            verbose=True,
        )
    )
    assert result.trace_path.exists()
    assert result.trace.get("final_answer")
    integrity = (result.auto_scores.get("trace_integrity") or {}).get("status")
    join_status = (result.auto_scores.get("join_integrity") or {}).get("status")
    answer_preview = (result.trace.get("final_answer") or "")[:500]
    print(f"\n[{case_id}] trace_integrity={integrity} join_integrity={join_status}")
    print(answer_preview.encode("ascii", errors="backslashreplace").decode("ascii"))
    assert integrity == "PASS", f"[{case_id}] auto_scores={result.auto_scores}"
