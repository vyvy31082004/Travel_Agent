import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL is required for PostgreSQL long-term memory integration test",
)


def test_postgres_memory_migration_contract_file_exists():
    migration = Path("alembic/versions/0005_long_term_memory.py")
    assert migration.exists()
    text = migration.read_text(encoding="utf-8")
    assert "long_term_memories" in text
    assert "memory_jobs" in text
    assert "memory_audit_records" in text
