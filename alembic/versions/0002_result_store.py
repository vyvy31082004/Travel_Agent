"""Create Result Store tables for search payloads.

Revision ID: 0002_result_store
Revises: 0001_initial
Create Date: 2026-07-26
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0002_result_store"
down_revision: str | Sequence[str] | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "search_runs" not in existing:
        op.create_table(
            "search_runs",
            sa.Column("search_id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("user_id", sa.Text(), nullable=False),
            sa.Column("thread_id", sa.Text(), nullable=False),
            sa.Column("request_id", sa.Text(), nullable=False),
            sa.Column("domain", sa.Text(), nullable=False),
            sa.Column(
                "query", postgresql.JSONB(astext_type=sa.Text()), nullable=False
            ),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column(
                "total_results", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )
    existing_indexes = {
        idx["name"] for idx in inspector.get_indexes("search_runs")
    } if "search_runs" in set(sa.inspect(bind).get_table_names()) else set()
    if "idx_search_thread" not in existing_indexes:
        op.create_index(
            "idx_search_thread",
            "search_runs",
            ["user_id", "thread_id", "created_at"],
        )

    existing = set(sa.inspect(bind).get_table_names())
    if "search_result_items" not in existing:
        op.create_table(
            "search_result_items",
            sa.Column(
                "search_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("search_runs.search_id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("item_id", sa.Text(), primary_key=True),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.Column(
                "payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False
            ),
            sa.Column("detail_token", sa.Text(), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "search_id",
                "position",
                name="uq_search_result_items_position",
            ),
        )
    item_indexes = {
        idx["name"] for idx in sa.inspect(bind).get_indexes("search_result_items")
    } if "search_result_items" in set(sa.inspect(bind).get_table_names()) else set()
    if "idx_item_position" not in item_indexes:
        op.create_index(
            "idx_item_position",
            "search_result_items",
            ["search_id", "position"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "search_result_items" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("search_result_items")}
        if "idx_item_position" in indexes:
            op.drop_index("idx_item_position", table_name="search_result_items")
        op.drop_table("search_result_items")
    tables = set(sa.inspect(bind).get_table_names())
    if "search_runs" in tables:
        indexes = {idx["name"] for idx in sa.inspect(bind).get_indexes("search_runs")}
        if "idx_search_thread" in indexes:
            op.drop_index("idx_search_thread", table_name="search_runs")
        op.drop_table("search_runs")
