from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.postgres import Base


class SearchRun(Base):
    __tablename__ = "search_runs"

    search_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    thread_id: Mapped[str] = mapped_column(Text, nullable=False)
    request_id: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str] = mapped_column(Text, nullable=False)
    query: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="completed")
    total_results: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    items: Mapped[list["SearchResultItem"]] = relationship(
        "SearchResultItem",
        back_populates="search_run",
        cascade="all, delete-orphan",
    )


class SearchResultItem(Base):
    __tablename__ = "search_result_items"
    __table_args__ = (
        UniqueConstraint(
            "search_id",
            "position",
            name="uq_search_result_items_position",
        ),
    )

    search_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("search_runs.search_id", ondelete="CASCADE"),
        primary_key=True,
    )
    item_id: Mapped[str] = mapped_column(Text, primary_key=True)
    api_position: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    eligible: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    search_run: Mapped["SearchRun"] = relationship(
        "SearchRun", back_populates="items"
    )
