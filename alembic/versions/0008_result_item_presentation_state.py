"""Add API and display presentation state to result items.

Revision ID: 0008_result_item_presentation
Revises: 0007_user_auth_sessions
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_result_item_presentation"
down_revision: str | Sequence[str] | None = "0007_user_auth_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Keep the immutable ordering returned by the upstream API separate from
    # the nullable position of items actually shown to the user.
    op.add_column(
        "search_result_items",
        sa.Column("api_position", sa.Integer(), nullable=True),
    )
    op.add_column(
        "search_result_items",
        sa.Column("eligible", sa.Boolean(), nullable=True),
    )
    op.execute(
        """
        UPDATE search_result_items
        SET api_position = position
        WHERE api_position IS NULL
        """
    )
    op.alter_column(
        "search_result_items",
        "api_position",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.alter_column(
        "search_result_items",
        "position",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.create_unique_constraint(
        "uq_search_result_items_api_position",
        "search_result_items",
        ["search_id", "api_position"],
    )


def downgrade() -> None:
    # Reconstruct the legacy full-list order before restoring NOT NULL. Display
    # decisions intentionally collapse back to the immutable API ordering.
    op.execute(
        """
        UPDATE search_result_items
        SET position = api_position
        """
    )
    op.alter_column(
        "search_result_items",
        "position",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.drop_constraint(
        "uq_search_result_items_api_position",
        "search_result_items",
        type_="unique",
    )
    op.drop_column("search_result_items", "eligible")
    op.drop_column("search_result_items", "api_position")
