"""
Live smoke test for travel planner flow.

Prints the final LLM itinerary when run with pytest -s:

  pytest tests/test_planner_flow_live.py -s -v

Requires GOOGLE_API_KEY or GEMINI_API_KEY (.env or environment) and MCP servers (8001-8004).
"""

import asyncio
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from planner_smoke_lib import (  # noqa: E402
    DEFAULT_PLANNER_MESSAGE,
    EMPTY_ANSWER,
    planner_smoke_ready,
    print_planner_output,
    run_planner_smoke,
)


@pytest.mark.live
@pytest.mark.skipif(
    not planner_smoke_ready(),
    reason="Requires GOOGLE_API_KEY/GEMINI_API_KEY and MCP servers on ports 8001-8004",
)
def test_planner_flow_prints_final_answer():
    payload = asyncio.run(
        run_planner_smoke(
            message=DEFAULT_PLANNER_MESSAGE,
            verbose=True,
        )
    )

    print_planner_output(payload)

    answer = payload["answer"]
    assert answer and answer != EMPTY_ANSWER
    branches = payload.get("domain_branch_results") or []
    assert len(branches) >= 1

    for branch in branches:
        domain = branch.get("domain")
        summary = (branch.get("summary") or "").lower()
        if domain in {"hotel", "car", "excursion"}:
            assert "completeorescalate" not in summary
            assert "không hỗ trợ chuyến bay" not in summary
            assert "không thuộc phạm vi chuyên môn" not in summary
