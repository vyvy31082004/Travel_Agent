"""Drop detail_token from search_result_items.

Flight detail tokens are stored inside payload JSONB instead.

Revision ID: 0004_drop_item_detail_token
Revises: 0003_drop_item_expires_at
Create Date: 2026-07-31
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0004_drop_item_detail_token"
down_revision: str | Sequence[str] | None = "0003_drop_item_expires_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "search_result_items" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("search_result_items")}
    if "detail_token" in columns:
        op.drop_column("search_result_items", "detail_token")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "search_result_items" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("search_result_items")}
    if "detail_token" not in columns:
        op.add_column(
            "search_result_items",
            sa.Column("detail_token", sa.Text(), nullable=True),
        )
