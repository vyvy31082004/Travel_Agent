from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from memory.long_term import TravelMemory

# TEMPORARY: default TTL for newly persisted memories without explicit validity.
DEFAULT_MEMORY_VALIDITY_DAYS = 3


def default_memory_validity_window(
    *,
    now: datetime | None = None,
    days: int = DEFAULT_MEMORY_VALIDITY_DAYS,
) -> tuple[datetime, datetime]:
    anchor = now or datetime.now(timezone.utc)
    return anchor, anchor + timedelta(days=days)


def apply_default_validity_if_missing(memory: TravelMemory) -> TravelMemory:
    if memory.valid_from is not None or memory.valid_to is not None:
        return memory
    valid_from, valid_to = default_memory_validity_window()
    return replace(memory, valid_from=valid_from, valid_to=valid_to)
