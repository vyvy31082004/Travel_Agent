#!/usr/bin/env python3
"""
Smoke test for the primary travel planner orchestration flow.

Requirements:
  - GOOGLE_API_KEY or GEMINI_API_KEY in .env or environment (Gemini LLM)
  - MCP servers on ports 8001-8004 (car, excursion, flight, hotel) for full domain search

Usage:
  # Terminal 1: start MCP servers (see project README)
  # Terminal 2 (key from .env or env var):
  python scripts/run_planner_smoke.py

  python scripts/run_planner_smoke.py --message "Lên kế hoạch 3 ngày 2 đêm Đà Nẵng từ TP.HCM: bay đi 05/09/2026, về 07/09/2026, check-in 05/09, check-out 07/09"
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from planner_smoke_lib import (  # noqa: E402
    DEFAULT_PLANNER_MESSAGE,
    has_llm_api_key,
    mcp_servers_available,
    print_planner_output,
    run_planner_smoke,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run travel planner smoke test and print the final LLM answer."
    )
    parser.add_argument(
        "--message",
        default=DEFAULT_PLANNER_MESSAGE,
        help="Trip planning user message",
    )
    return parser.parse_args()


async def main() -> int:
    if not has_llm_api_key():
        print(
            "Error: set GOOGLE_API_KEY or GEMINI_API_KEY in .env or environment.",
            file=sys.stderr,
        )
        return 1
    if not mcp_servers_available():
        print(
            "Error: MCP servers not reachable on 127.0.0.1:8001-8004. "
            "Start them first (see README).",
            file=sys.stderr,
        )
        return 1

    args = parse_args()
    print("Running planner smoke test (live LLM + MCP)...")
    print(f"Message: {args.message}\n")

    payload = await run_planner_smoke(message=args.message, verbose=True)
    print_planner_output(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
