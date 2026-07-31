"""Drop redundant expires_at from search_result_items.

TTL is enforced only via search_runs.expires_at.

Revision ID: 0003_drop_item_expires_at
Revises: 0002_result_store
Create Date: 2026-07-30
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0003_drop_item_expires_at"
down_revision: str | Sequence[str] | None = "0002_result_store"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "search_result_items" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("search_result_items")}
    if "expires_at" in columns:
        op.drop_column("search_result_items", "expires_at")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "search_result_items" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("search_result_items")}
    if "expires_at" not in columns:
        op.add_column(
            "search_result_items",
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        )
