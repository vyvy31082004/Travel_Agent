"""add long term memory tables

Revision ID: 0005_long_term_memory
Revises: 0004_drop_item_detail_token
Create Date: 2026-08-05 15:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0005_long_term_memory"
down_revision: Union[str, None] = "0004_drop_item_detail_token"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


MEMORY_STATUS = ("active", "superseded", "deleted")
JOB_STATUS = ("pending", "processing", "completed", "failed", "skipped")
AUDIT_DECISION = ("approve", "reject", "retry", "fail", "noop")


def upgrade() -> None:
    op.create_table(
        "long_term_memories",
        sa.Column(
            "memory_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("family", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("memory_text", sa.Text(), nullable=False),
        sa.Column("condition", sa.Text(), nullable=True),
        sa.Column("evidence_text", sa.Text(), nullable=False),
        sa.Column("source_thread_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "supersedes_memory_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "long_term_memories.memory_id",
                name="fk_long_term_memories_supersedes_memory_id",
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            f"status IN {MEMORY_STATUS}",
            name="ck_long_term_memories_status",
        ),
        sa.CheckConstraint(
            "char_length(memory_text) BETWEEN 3 AND 500",
            name="ck_long_term_memories_text_length",
        ),
    )
    op.create_index(
        "ix_long_term_memories_user_family_status",
        "long_term_memories",
        ["user_id", "family", "status"],
    )
    op.create_index(
        "ix_long_term_memories_user_category_status",
        "long_term_memories",
        ["user_id", "category", "status"],
    )
    op.create_index(
        "ix_long_term_memories_source_thread",
        "long_term_memories",
        ["source_thread_id"],
    )
    op.create_index(
        "ix_long_term_memories_metadata_gin",
        "long_term_memories",
        ["metadata"],
        postgresql_using="gin",
    )

    op.create_table(
        "memory_jobs",
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("final_message_id", sa.Text(), nullable=True),
        sa.Column("checkpoint_id", sa.Text(), nullable=True),
        sa.Column(
            "messages",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_memory_jobs_idempotency_key",
        ),
        sa.CheckConstraint(f"status IN {JOB_STATUS}", name="ck_memory_jobs_status"),
        sa.CheckConstraint("attempts >= 0", name="ck_memory_jobs_attempts_non_negative"),
    )
    op.create_index("ix_memory_jobs_status_created", "memory_jobs", ["status", "created_at"])
    op.create_index("ix_memory_jobs_user_thread", "memory_jobs", ["user_id", "thread_id"])

    op.create_table(
        "memory_audit_records",
        sa.Column(
            "audit_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("memory_jobs.job_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("thread_id", sa.Text(), nullable=True),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column(
            "proposed_transition",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "rule_result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "verifier_result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "affected_memory_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            f"decision IN {AUDIT_DECISION}",
            name="ck_memory_audit_records_decision",
        ),
    )
    op.create_index("ix_memory_audit_records_job_id", "memory_audit_records", ["job_id"])
    op.create_index(
        "ix_memory_audit_records_user_created",
        "memory_audit_records",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_memory_audit_records_user_created", table_name="memory_audit_records")
    op.drop_index("ix_memory_audit_records_job_id", table_name="memory_audit_records")
    op.drop_table("memory_audit_records")

    op.drop_index("ix_memory_jobs_user_thread", table_name="memory_jobs")
    op.drop_index("ix_memory_jobs_status_created", table_name="memory_jobs")
    op.drop_table("memory_jobs")

    op.drop_index("ix_long_term_memories_metadata_gin", table_name="long_term_memories")
    op.drop_index("ix_long_term_memories_source_thread", table_name="long_term_memories")
    op.drop_index("ix_long_term_memories_user_category_status", table_name="long_term_memories")
    op.drop_index("ix_long_term_memories_user_family_status", table_name="long_term_memories")
    op.drop_table("long_term_memories")
