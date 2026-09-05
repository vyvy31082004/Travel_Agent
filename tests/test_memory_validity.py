from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memory.long_term import MemoryCategory, MemoryDomain, TravelMemory
from memory.validity import (
    DEFAULT_MEMORY_VALIDITY_DAYS,
    apply_default_validity_if_missing,
    default_memory_validity_window,
)


def _sample_memory(**overrides) -> TravelMemory:
    base = dict(
        user_id="user_a",
        memory_text="Thích khách sạn yên tĩnh",
        category=MemoryCategory.HOTEL_PREFERENCE,
        domain=MemoryDomain.HOTEL,
        evidence_text="Thích khách sạn yên tĩnh",
        source_thread_id="thread-1",
    )
    base.update(overrides)
    return TravelMemory(**base)


def test_apply_default_validity_sets_three_day_window() -> None:
    memory = apply_default_validity_if_missing(_sample_memory())
    assert memory.valid_from is not None
    assert memory.valid_to is not None
    assert memory.valid_to - memory.valid_from == timedelta(days=DEFAULT_MEMORY_VALIDITY_DAYS)


def test_apply_default_validity_preserves_explicit_values() -> None:
    valid_from = datetime(2026, 1, 1, tzinfo=timezone.utc)
    valid_to = datetime(2026, 12, 31, tzinfo=timezone.utc)
    memory = apply_default_validity_if_missing(
        _sample_memory(valid_from=valid_from, valid_to=valid_to)
    )
    assert memory.valid_from == valid_from
    assert memory.valid_to == valid_to


def test_default_memory_validity_window_anchor() -> None:
    anchor = datetime(2026, 9, 1, tzinfo=timezone.utc)
    valid_from, valid_to = default_memory_validity_window(now=anchor)
    assert valid_from == anchor
    assert valid_to == anchor + timedelta(days=3)
