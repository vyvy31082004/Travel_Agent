"""add pgvector memory embeddings

Revision ID: 0006_pgvector_memory_embeddings
Revises: 0005_long_term_memory
Create Date: 2026-08-05 16:30:00.000000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0006_pgvector_memory_embeddings"
down_revision: Union[str, None] = "0005_long_term_memory"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBED_DIMS = 3072


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS long_term_memory_embeddings (
            embedding_id uuid PRIMARY KEY,
            memory_id uuid NOT NULL REFERENCES long_term_memories(memory_id) ON DELETE CASCADE,
            embedding vector({EMBED_DIMS}) NOT NULL,
            embedding_model text NOT NULL,
            embedding_dims integer NOT NULL,
            content_hash text NOT NULL,
            is_current boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_long_term_memory_embeddings_dims
                CHECK (embedding_dims = {EMBED_DIMS}),
            CONSTRAINT uq_long_term_memory_embeddings_memory_model_hash
                UNIQUE (memory_id, embedding_model, content_hash)
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_long_term_memory_embeddings_current
        ON long_term_memory_embeddings (memory_id, embedding_model, embedding_dims)
        WHERE is_current = true
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_long_term_memory_embeddings_lookup
        ON long_term_memory_embeddings (memory_id, embedding_model, embedding_dims, is_current)
        """
    )
    if EMBED_DIMS <= 2000:
        op.execute(
            """
            DO $$
            BEGIN
                CREATE INDEX IF NOT EXISTS ix_long_term_memory_embeddings_vector_hnsw
                ON long_term_memory_embeddings
                USING hnsw (embedding vector_cosine_ops)
                WHERE is_current = true;
            EXCEPTION
                WHEN undefined_object OR feature_not_supported OR program_limit_exceeded THEN
                    CREATE INDEX IF NOT EXISTS ix_long_term_memory_embeddings_vector_ivfflat
                    ON long_term_memory_embeddings
                    USING ivfflat (embedding vector_cosine_ops)
                    WITH (lists = 100)
                    WHERE is_current = true;
            END
            $$;
            """
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_long_term_memory_embeddings_vector_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_long_term_memory_embeddings_vector_ivfflat")
    op.execute("DROP INDEX IF EXISTS ix_long_term_memory_embeddings_lookup")
    op.execute("DROP INDEX IF EXISTS uq_long_term_memory_embeddings_current")
    op.execute("DROP TABLE IF EXISTS long_term_memory_embeddings")
