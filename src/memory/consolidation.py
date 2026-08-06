from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Sequence

from memory.long_term import MemoryCategory, MemoryDomain, TravelMemory
from services.long_term_memory import serialize_message


class TransitionAction(StrEnum):
    INSERT = "insert"
    UPDATE = "update"
    SUPERSEDE = "supersede"
    REJECT = "reject"
    NOOP = "noop"


@dataclass(frozen=True)
class RuleResult:
    ok: bool
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MemoryTransition:
    action: TransitionAction
    candidate: TravelMemory | None = None
    existing_memory_id: str | None = None
    reasons: list[str] = field(default_factory=list)


def extract_candidate_memories(
    messages: Sequence[dict[str, Any] | Any],
    *,
    user_id: str,
    thread_id: str,
    limit: int = 5,
) -> list[TravelMemory]:
    """Extract durable memory candidates from bounded turn messages.

    This deterministic adapter is intentionally conservative. It provides a
    testable baseline while LangMem/package choices remain unpinned.
    """

    candidates: list[TravelMemory] = []
    for message in messages:
        serialized = serialize_message(message)
        if serialized.get("type") not in {"human", "user"}:
            continue
        text = str(serialized.get("content") or "").strip()
        if not _looks_like_durable_user_evidence(text):
            continue
        memory_text = _clean_memory_text(text)
        if len(memory_text) < 3:
            continue
        category, domain = classify_memory(memory_text)
        try:
            candidates.append(
                TravelMemory(
                    user_id=user_id,
                    memory_text=memory_text,
                    category=category,
                    domain=domain,
                    condition=_extract_condition(memory_text),
                    evidence_text=text,
                    source_thread_id=thread_id,
                )
            )
        except ValueError:
            continue
        if len(candidates) >= limit:
            break
    return candidates


def validate_memory_candidate(candidate: TravelMemory) -> RuleResult:
    reasons: list[str] = []
    if not candidate.evidence_text.strip():
        reasons.append("missing user evidence")
    if len(candidate.memory_text) > 500:
        reasons.append("memory text is too long")
    lowered = candidate.evidence_text.lower()
    if any(token in lowered for token in _SENSITIVE_TOKENS):
        reasons.append("contains sensitive credential or payment data")
    if any(token in lowered for token in _TOOL_ONLY_MARKERS):
        reasons.append("appears to be tool/API output rather than user evidence")
    if _is_ambiguous(lowered):
        reasons.append("evidence is ambiguous")
    return RuleResult(ok=not reasons, reasons=reasons)


def calculate_transition(
    candidate: TravelMemory,
    existing_active: Sequence[TravelMemory],
) -> MemoryTransition:
    rule_result = validate_memory_candidate(candidate)
    if not rule_result.ok:
        return MemoryTransition(
            action=TransitionAction.REJECT,
            candidate=candidate,
            reasons=rule_result.reasons,
        )

    normalized_candidate = _normalize_statement(candidate.memory_text)
    for existing in existing_active:
        normalized_existing = _normalize_statement(existing.memory_text)
        if normalized_candidate == normalized_existing:
            return MemoryTransition(
                action=TransitionAction.NOOP,
                candidate=candidate,
                existing_memory_id=existing.memory_id,
                reasons=["duplicate active memory"],
            )
        if (
            candidate.category == existing.category
            and candidate.domain == existing.domain
            and _looks_conflicting(normalized_candidate, normalized_existing)
        ):
            return MemoryTransition(
                action=TransitionAction.SUPERSEDE,
                candidate=candidate,
                existing_memory_id=existing.memory_id,
                reasons=["same category/domain with conflicting preference"],
            )

    return MemoryTransition(action=TransitionAction.INSERT, candidate=candidate)


def _looks_like_durable_user_evidence(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _DURABLE_MARKERS)


def _clean_memory_text(text: str) -> str:
    cleaned = " ".join(text.strip().split())
    prefixes = [
        "hãy nhớ rằng",
        "hãy nhớ",
        "nhớ là",
        "tôi thích",
        "tôi thường",
        "tôi ưu tiên",
        "ưu tiên của tôi là",
        "i prefer",
        "remember that",
        "please remember",
    ]
    lowered = cleaned.lower()
    for prefix in prefixes:
        if lowered.startswith(prefix):
            return cleaned[len(prefix) :].strip(" :,-.") or cleaned
    return cleaned


def classify_memory(text: str) -> tuple[MemoryCategory, MemoryDomain]:
    lowered = text.lower()
    if any(token in lowered for token in ["hotel", "khách sạn", "resort", "homestay"]):
        return MemoryCategory.HOTEL_PREFERENCE, MemoryDomain.HOTEL
    if any(token in lowered for token in ["flight", "bay", "chuyến bay", "sân bay"]):
        return MemoryCategory.FLIGHT_PREFERENCE, MemoryDomain.FLIGHT
    if any(token in lowered for token in ["xe", "car", "thuê xe", "tài xế"]):
        return MemoryCategory.CAR_PREFERENCE, MemoryDomain.CAR
    if any(token in lowered for token in ["tour", "excursion", "tham quan", "hoạt động"]):
        return MemoryCategory.EXCURSION_PREFERENCE, MemoryDomain.EXCURSION
    if any(token in lowered for token in ["gọi tôi", "tên tôi", "my name", "home airport"]):
        return MemoryCategory.PROFILE_FACT, MemoryDomain.GENERAL
    if any(token in lowered for token in ["trả lời", "answer", "luôn", "đừng"]):
        return MemoryCategory.INTERACTION_RULE, MemoryDomain.GENERAL
    return MemoryCategory.GENERAL_PREFERENCE, MemoryDomain.GENERAL


def _extract_condition(text: str) -> str | None:
    lowered = text.lower()
    for marker in ["khi đi công tác", "khi đi gia đình", "business", "family trip"]:
        if marker in lowered:
            return marker
    return None


def _normalize_statement(text: str) -> str:
    return " ".join(text.lower().strip().strip(".!?").split())


def _is_ambiguous(lowered: str) -> bool:
    return any(token in lowered for token in ["có thể", "maybe", "perhaps", "không chắc"])


def _looks_conflicting(left: str, right: str) -> bool:
    positive = ["thích", "prefer", "ưu tiên", "muốn"]
    negative = ["không thích", "don't like", "do not like", "tránh", "avoid"]
    return (
        any(token in left for token in positive) and any(token in right for token in negative)
    ) or (
        any(token in left for token in negative) and any(token in right for token in positive)
    )


_DURABLE_MARKERS = [
    "hãy nhớ",
    "nhớ là",
    "tôi thích",
    "tôi không thích",
    "tôi thường",
    "tôi ưu tiên",
    "ưu tiên của tôi",
    "gọi tôi",
    "tên tôi",
    "i prefer",
    "i usually",
    "remember that",
    "please remember",
]

_SENSITIVE_TOKENS = [
    "số hộ chiếu",
    "passport number",
    "credit card",
    "thẻ tín dụng",
    "cvv",
    "mật khẩu",
    "password",
]

_TOOL_ONLY_MARKERS = [
    "search_id",
    "displayed_item_ids",
    "total_results",
    "item_id",
]
