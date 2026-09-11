from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from psycopg_pool import AsyncConnectionPool

from e2e_eval.schema import E2ECase, SeedMemory
from memory.long_term import (
    MemoryCategory,
    MemoryStatus,
    TravelMemory,
)
from memory.validity import default_memory_validity_window
from psycopg.types.json import Jsonb

from repositories.long_term_memory import PostgresLongTermMemoryRepository
from settings import Settings

UPSERT_E2E_MEMORY_SQL = """
    INSERT INTO long_term_memories (
        memory_id, user_id, family, category, domain, memory_text,
        condition, evidence_text, source_thread_id, status,
        valid_from, valid_to, supersedes_memory_id, metadata
    ) VALUES (
        %(memory_id)s, %(user_id)s, %(family)s, %(category)s,
        %(domain)s, %(memory_text)s, %(condition)s,
        %(evidence_text)s, %(source_thread_id)s, %(status)s,
        %(valid_from)s, %(valid_to)s, %(supersedes_memory_id)s,
        %(metadata)s
    )
    ON CONFLICT (memory_id) DO UPDATE SET
        user_id = EXCLUDED.user_id,
        family = EXCLUDED.family,
        category = EXCLUDED.category,
        domain = EXCLUDED.domain,
        memory_text = EXCLUDED.memory_text,
        condition = EXCLUDED.condition,
        evidence_text = EXCLUDED.evidence_text,
        source_thread_id = EXCLUDED.source_thread_id,
        status = EXCLUDED.status,
        valid_from = EXCLUDED.valid_from,
        valid_to = EXCLUDED.valid_to,
        supersedes_memory_id = EXCLUDED.supersedes_memory_id,
        metadata = EXCLUDED.metadata,
        updated_at = now()
"""

E2E_NAMESPACE = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")

DOMAIN_DEFAULT_CATEGORY: dict[str, MemoryCategory] = {
    "hotel": MemoryCategory.HOTEL_PREFERENCE,
    "flight": MemoryCategory.FLIGHT_PREFERENCE,
    "car": MemoryCategory.CAR_PREFERENCE,
    "excursion": MemoryCategory.EXCURSION_PREFERENCE,
    "general": MemoryCategory.INTERACTION_RULE,
    "planner": MemoryCategory.GENERAL_PREFERENCE,
}


def e2e_user_id(case_id: str, original_user_id: str) -> str:
    return f"e2e-{case_id}:{original_user_id}"


def e2e_user_prefix(case_id: str) -> str:
    return f"e2e-{case_id}:%"


def e2e_thread_id(case_id: str, run_id: str) -> str:
    return f"e2e-{case_id}-{run_id}"


def seeded_memory_uuid(case_id: str, fixture_memory_id: str) -> uuid.UUID:
    return uuid.uuid5(E2E_NAMESPACE, f"e2e-eval:{case_id}:{fixture_memory_id}")


@dataclass(frozen=True)
class SeedResult:
    case_user_id: str
    thread_id: str
    fixture_to_uuid: dict[str, str]
    seeded_uuids: set[str]


def _seed_memory_to_travel_memory(
    seed: SeedMemory,
    *,
    case_id: str,
    case_user_id: str,
    thread_id: str,
) -> TravelMemory:
    domain = seed.domain or "general"
    category = seed.category or str(
        DOMAIN_DEFAULT_CATEGORY.get(domain, MemoryCategory.GENERAL_PREFERENCE)
    )
    memory_user = e2e_user_id(case_id, seed.user_id or case_user_id.split(":", 1)[-1])
    metadata: dict[str, Any] = {"fixture_id": seed.id}
    if seed.family:
        metadata["family_override"] = seed.family
    valid_from, valid_to = default_memory_validity_window()
    return TravelMemory(
        memory_id=str(seeded_memory_uuid(case_id, seed.id)),
        user_id=memory_user,
        memory_text=seed.text,
        category=category,
        domain=domain,
        evidence_text=seed.evidence_text or seed.text,
        source_thread_id=thread_id,
        status=MemoryStatus(seed.status),
        valid_from=valid_from,
        valid_to=valid_to,
        metadata=metadata,
    )


async def seed_case_memories(
    case: E2ECase,
    *,
    pool: AsyncConnectionPool,
    repository: PostgresLongTermMemoryRepository | None = None,
    run_id: str,
    settings: Settings | None = None,
) -> SeedResult:
    """Insert active memories via SQL — recall uses fetch_active_domain_memories, not pgvector."""
    _ = repository, settings
    case_id = case.id
    case_user = e2e_user_id(case_id, case.seed.user_id)
    thread_id = e2e_thread_id(case_id, run_id)
    fixture_to_uuid: dict[str, str] = {}
    seeded_uuids: set[str] = set()

    for seed in case.seed.long_term_memories:
        memory = _seed_memory_to_travel_memory(
            seed,
            case_id=case_id,
            case_user_id=case_user,
            thread_id=thread_id,
        )
        seeded = seeded_memory_uuid(case_id, seed.id)
        fixture_to_uuid[seed.id] = str(seeded)
        seeded_uuids.add(str(seeded))
        await _upsert_e2e_memory(
            pool,
            memory=memory,
            seeded_uuid_value=seeded,
            user_id=memory.user_id or case_user,
        )

    return SeedResult(
        case_user_id=case_user,
        thread_id=thread_id,
        fixture_to_uuid=fixture_to_uuid,
        seeded_uuids=seeded_uuids,
    )


async def _upsert_e2e_memory(
    pool: AsyncConnectionPool,
    *,
    memory: TravelMemory,
    seeded_uuid_value: uuid.UUID,
    user_id: str,
) -> None:
    record = memory.to_record()
    async with pool.connection() as conn:
        await conn.execute(
            UPSERT_E2E_MEMORY_SQL,
            {
                **record,
                "memory_id": seeded_uuid_value,
                "user_id": user_id,
                "metadata": Jsonb(record.get("metadata") or {}),
            },
        )
