import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def test_postgres_memory_migration_contract_file_exists():
    migration = Path("alembic/versions/0005_long_term_memory.py")
    assert migration.exists()
    text = migration.read_text(encoding="utf-8")
    assert "long_term_memories" in text
    assert "memory_jobs" in text
    assert "memory_audit_records" in text


def test_pgvector_memory_embedding_migration_contract_file_exists():
    migration = Path("alembic/versions/0006_pgvector_memory_embeddings.py")
    assert migration.exists()
    text = migration.read_text(encoding="utf-8")
    assert "CREATE EXTENSION IF NOT EXISTS vector" in text
    assert "long_term_memory_embeddings" in text
    assert "embedding vector({EMBED_DIMS})" in text
    assert "EMBED_DIMS = 3072" in text
    assert "vector_cosine_ops" in text
    assert "ON DELETE CASCADE" in text


def test_semantic_search_sql_contains_mandatory_filters():
    source = Path("src/repositories/long_term_memory.py").read_text(encoding="utf-8")
    assert "m.user_id = %(user_id)s" in source
    assert "m.family = ANY(%(families)s)" in source
    assert "m.status = 'active'" in source
    assert "e.is_current = true" in source
    assert "e.embedding_model = %(embedding_model)s" in source
    assert "e.embedding_dims = %(embedding_dims)s" in source
    assert "<= %(distance_threshold)s" in source


@pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL is required for PostgreSQL pgvector integration test",
)
def test_pgvector_database_objects_available_when_migrated():
    import psycopg

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.long_term_memory_embeddings')")
            assert cur.fetchone()[0] == "long_term_memory_embeddings"
            cur.execute("SELECT extname FROM pg_extension WHERE extname = 'vector'")
            assert cur.fetchone()[0] == "vector"
