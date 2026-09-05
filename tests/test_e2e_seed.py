from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from e2e_eval.schema import SeedMemory
from e2e_eval.seed import _seed_memory_to_travel_memory
from memory.validity import (
    DEFAULT_MEMORY_VALIDITY_DAYS,
    default_memory_validity_window,
)


def test_default_memory_validity_window_is_three_days() -> None:
    anchor = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    valid_from, valid_to = default_memory_validity_window(now=anchor)
    assert valid_from == anchor
    assert valid_to == anchor + timedelta(days=DEFAULT_MEMORY_VALIDITY_DAYS)


def test_seed_memory_sets_validity_window() -> None:
    memory = _seed_memory_to_travel_memory(
        SeedMemory(id="m_budget", text="Budget 1-2 triệu", domain="hotel"),
        case_id="e2e_hotel_001",
        case_user_id="e2e-e2e_hotel_001:user_a",
        thread_id="e2e-e2e_hotel_001-test",
    )
    assert memory.valid_from is not None
    assert memory.valid_to is not None
    assert memory.valid_to - memory.valid_from == timedelta(days=3)
    assert memory.is_active
