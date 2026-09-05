from __future__ import annotations

import re
from typing import Sequence

from memory.applicability import ApplicabilityJudgment, ApplicabilityLabel
from memory.long_term import TravelMemory

_BUDGET_RANGE_RE = re.compile(
    r"(\d+)\s*[–\-]\s*(\d+)\s*triệu",
    re.IGNORECASE,
)
_BUDGET_MAX_RE = re.compile(
    r"(?:tối đa|dưới|max)\s*(\d+)\s*triệu",
    re.IGNORECASE,
)


def _parse_budget_hints(text: str) -> list[str]:
    hints: list[str] = []
    match = _BUDGET_RANGE_RE.search(text)
    if match:
        low = int(match.group(1)) * 1_000_000
        high = int(match.group(2)) * 1_000_000
        hints.append(f"price_min={low}")
        hints.append(f"price_max={high}")
        return hints
    match = _BUDGET_MAX_RE.search(text)
    if match:
        high = int(match.group(1)) * 1_000_000
        hints.append(f"price_max={high}")
    return hints


def derive_turn_constraints(
    memories: Sequence[TravelMemory],
    judgments: Sequence[ApplicabilityJudgment],
    *,
    domain: str,
) -> list[str]:
    """Derive machine-readable turn constraints from apply/uncertain memories."""
    label_by_id = {item.memory_id: item.label for item in judgments}
    hints: list[str] = []
    seen: set[str] = set()

    def add(item: str) -> None:
        if item not in seen:
            seen.add(item)
            hints.append(item)

    for memory in memories:
        memory_id = str(memory.memory_id or "")
        label = label_by_id.get(memory_id)
        if label not in {ApplicabilityLabel.APPLY, ApplicabilityLabel.UNCERTAIN}:
            continue
        text = (memory.memory_text or "").lower()
        if domain == "hotel":
            if "ngân sách" in text or "triệu" in text:
                for hint in _parse_budget_hints(text):
                    add(hint)
        elif domain == "flight":
            if label == ApplicabilityLabel.APPLY and (
                "sgn" in text or "tp.hcm" in text or "hồ chí minh" in text
            ):
                add("origin=SGN")
            if label == ApplicabilityLabel.APPLY and any(
                token in text for token in ("phổ thông", "economy", "hạng phổ thông")
            ):
                add("cabin_class=economy")
            if label == ApplicabilityLabel.APPLY and any(
                token in text
                for token in ("bay thẳng", "thẳng", "direct", "tránh nối")
            ):
                add("prefer_direct=true")
        elif domain == "car":
            if label == ApplicabilityLabel.APPLY and (
                "tự động" in text or "automatic" in text
            ):
                add("transmission=automatic")
            if label == ApplicabilityLabel.APPLY and (
                "7 chỗ" in text or "bảy chỗ" in text or "tối thiểu 7" in text
            ):
                add("min_seats=7")
        elif domain == "excursion":
            if label == ApplicabilityLabel.APPLY and any(
                token in text for token in ("thiên nhiên", "nature")
            ):
                add("prefer_nature=true")

    return hints


def merge_turn_constraints(
    existing: Sequence[str] | None,
    derived: Sequence[str],
) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for item in list(existing or []) + list(derived):
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        merged.append(text)
    return merged
