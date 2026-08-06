from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal


class MemoryCategory(StrEnum):
    FLIGHT_PREFERENCE = "flight_preference"
    HOTEL_PREFERENCE = "hotel_preference"
    CAR_PREFERENCE = "car_preference"
    EXCURSION_PREFERENCE = "excursion_preference"
    GENERAL_PREFERENCE = "general_preference"
    PROFILE_FACT = "profile_fact"
    INTERACTION_RULE = "interaction_rule"


class MemoryDomain(StrEnum):
    FLIGHT = "flight"
    HOTEL = "hotel"
    CAR = "car"
    EXCURSION = "excursion"
    PLANNER = "planner"
    GENERAL = "general"


class MemoryFamily(StrEnum):
    TRAVEL_PREFERENCES = "travel_preferences"
    PROFILE_FACTS = "profile_facts"
    INTERACTION_RULES = "interaction_rules"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DELETED = "deleted"


CATEGORY_FAMILY: dict[MemoryCategory, MemoryFamily] = {
    MemoryCategory.FLIGHT_PREFERENCE: MemoryFamily.TRAVEL_PREFERENCES,
    MemoryCategory.HOTEL_PREFERENCE: MemoryFamily.TRAVEL_PREFERENCES,
    MemoryCategory.CAR_PREFERENCE: MemoryFamily.TRAVEL_PREFERENCES,
    MemoryCategory.EXCURSION_PREFERENCE: MemoryFamily.TRAVEL_PREFERENCES,
    MemoryCategory.GENERAL_PREFERENCE: MemoryFamily.TRAVEL_PREFERENCES,
    MemoryCategory.PROFILE_FACT: MemoryFamily.PROFILE_FACTS,
    MemoryCategory.INTERACTION_RULE: MemoryFamily.INTERACTION_RULES,
}


@dataclass(frozen=True)
class TravelMemory:
    memory_text: str
    category: MemoryCategory | str
    domain: MemoryDomain | str
    evidence_text: str
    source_thread_id: str
    memory_id: str | None = None
    user_id: str | None = None
    condition: str | None = None
    status: MemoryStatus | str = MemoryStatus.ACTIVE
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    supersedes_memory_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        memory_text = self.memory_text.strip()
        evidence_text = self.evidence_text.strip()
        source_thread_id = self.source_thread_id.strip()
        if len(memory_text) < 3:
            raise ValueError("memory_text must be at least 3 characters")
        if len(memory_text) > 500:
            raise ValueError("memory_text must be at most 500 characters")
        if not evidence_text:
            raise ValueError("evidence_text is required")
        if not source_thread_id:
            raise ValueError("source_thread_id is required")
        object.__setattr__(self, "memory_text", memory_text)
        object.__setattr__(self, "evidence_text", evidence_text)
        object.__setattr__(self, "source_thread_id", source_thread_id)
        object.__setattr__(self, "category", MemoryCategory(str(self.category)))
        object.__setattr__(self, "domain", MemoryDomain(str(self.domain)))
        object.__setattr__(self, "status", MemoryStatus(str(self.status)))
        if self.condition is not None:
            condition = self.condition.strip() or None
            object.__setattr__(self, "condition", condition)

    @property
    def family(self) -> MemoryFamily:
        return CATEGORY_FAMILY[MemoryCategory(self.category)]

    @property
    def is_active(self) -> bool:
        now = datetime.now(timezone.utc)
        if MemoryStatus(self.status) != MemoryStatus.ACTIVE:
            return False
        if self.valid_from and self.valid_from > now:
            return False
        if self.valid_to and self.valid_to <= now:
            return False
        return True

    def to_record(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "user_id": self.user_id,
            "memory_text": self.memory_text,
            "category": str(self.category),
            "domain": str(self.domain),
            "family": str(self.family),
            "condition": self.condition,
            "evidence_text": self.evidence_text,
            "source_thread_id": self.source_thread_id,
            "status": str(self.status),
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "supersedes_memory_id": self.supersedes_memory_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "TravelMemory":
        return cls(
            memory_id=str(record["memory_id"]) if record.get("memory_id") else None,
            user_id=str(record["user_id"]) if record.get("user_id") else None,
            memory_text=str(record["memory_text"]),
            category=str(record["category"]),
            domain=str(record["domain"]),
            condition=record.get("condition"),
            evidence_text=str(record["evidence_text"]),
            source_thread_id=str(record["source_thread_id"]),
            status=str(record.get("status") or MemoryStatus.ACTIVE),
            valid_from=record.get("valid_from"),
            valid_to=record.get("valid_to"),
            supersedes_memory_id=(
                str(record["supersedes_memory_id"])
                if record.get("supersedes_memory_id")
                else None
            ),
            created_at=record.get("created_at"),
            updated_at=record.get("updated_at"),
            metadata=dict(record.get("metadata") or {}),
        )


def memory_namespace(user_id: str, family: MemoryFamily | str) -> tuple[str, str, str]:
    user = str(user_id).strip()
    if not user:
        raise ValueError("user_id is required")
    return ("users", user, str(MemoryFamily(str(family))))


def namespace_for_category(
    user_id: str, category: MemoryCategory | str
) -> tuple[str, str, str]:
    return memory_namespace(user_id, CATEGORY_FAMILY[MemoryCategory(str(category))])


def format_memory_for_prompt(memory: TravelMemory) -> str:
    condition = f" (điều kiện: {memory.condition})" if memory.condition else ""
    return f"[{memory.memory_id or 'memory'}] {memory.memory_text}{condition}"
