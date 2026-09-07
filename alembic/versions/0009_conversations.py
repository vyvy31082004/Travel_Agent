"""Add conversations table mapping chat threads to owning users.

Revision ID: 0009_conversations
Revises: 0008_result_item_presentation
Create Date: 2026-09-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_conversations"
down_revision: str | Sequence[str] | None = "0008_result_item_presentation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Message content lives in the LangGraph checkpointer (keyed by thread_id);
    # this table only records ownership + display metadata so a user's threads
    # can be listed and reopened.
    op.create_table(
        "conversations",
        sa.Column("thread_id", sa.Text(), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("preview", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_conversations_user_updated",
        "conversations",
        ["user_id", sa.text("updated_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_user_updated", table_name="conversations")
    op.drop_table("conversations")
