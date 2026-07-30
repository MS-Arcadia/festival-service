"""SQLAlchemy tables.

Deliberately separate from the domain classes, for the same reason every other
service on this platform keeps the split: a ``Festival`` in ``app/domain`` has
invariants and no idea a database exists; these are rows. The repositories map
between them.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.platform.db import Base


class FestivalRow(Base):
    __tablename__ = "festivals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    state: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Optimistic concurrency: two admins acting on the same festival at once
    # cannot both write the same version.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    games: Mapped[list[FestivalGameRow]] = relationship(
        back_populates="festival",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="FestivalGameRow.added_at",
    )


class FestivalGameRow(Base):
    __tablename__ = "festival_games"

    festival_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("festivals.id", ondelete="CASCADE"), primary_key=True
    )
    game_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    developer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    added_by: Mapped[str] = mapped_column(String(64), nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    festival: Mapped[FestivalRow] = relationship(back_populates="games")


class CatalogGameRow(Base):
    """The read-model built from ``game-events``: what this service knows about a
    game without asking Catalog for it."""

    __tablename__ = "catalog_games"

    game_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    developer_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PromotionSnapshotRow(Base):
    """The read-model of Catalog's promotions, scoped to festivals this service
    has selected the game into."""

    __tablename__ = "promotion_snapshots"

    promotion_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    festival_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    game_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    discount_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    list_price_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    list_price_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    effective_price_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    effective_price_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
