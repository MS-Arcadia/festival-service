rom __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.domain.catalog_sync import PromotionSnapshot
from app.domain.festival import Festival, FestivalGame, FestivalState
from app.platform.money import Money


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


class MoneyView(BaseModel):
    amount_minor: str
    currency: str

    @classmethod
    def of(cls, money: Money | None) -> MoneyView | None:
        if money is None:
            return None
        return cls(**money.to_wire())




class CreateFestivalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    description: str = Field(default="", max_length=4_000)
    starts_at: datetime
    ends_at: datetime


class RescheduleFestivalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    starts_at: datetime
    ends_at: datetime


class AddGameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    game_id: Annotated[str, StringConstraints(min_length=1, max_length=64)]




class FestivalGameView(BaseModel):
    game_id: str
    title: str
    developer_id: str
    added_by: str
    added_at: datetime
    discounted_price: MoneyView | None = None
    discount_bps: int | None = None

    @classmethod
    def of(
        cls, game: FestivalGame, *, active_promotion: PromotionSnapshot | None
    ) -> FestivalGameView:
        return cls(
            game_id=game.game_id,
            title=game.title,
            developer_id=game.developer_id,
            added_by=game.added_by,
            added_at=game.added_at,
            discounted_price=MoneyView.of(active_promotion.effective_price)
            if active_promotion
            else None,
            discount_bps=active_promotion.discount_bps if active_promotion else None,
        )


class PromotionSnapshotView(BaseModel):
    promotion_id: str
    game_id: str
    state: str
    discount_bps: int
    starts_at: datetime
    ends_at: datetime
    list_price: MoneyView | None
    effective_price: MoneyView | None
    updated_at: datetime

    @classmethod
    def of(cls, snapshot: PromotionSnapshot) -> PromotionSnapshotView:
        return cls(
            promotion_id=snapshot.promotion_id,
            game_id=snapshot.game_id,
            state=snapshot.state,
            discount_bps=snapshot.discount_bps,
            starts_at=snapshot.starts_at,
            ends_at=snapshot.ends_at,
            list_price=MoneyView.of(snapshot.list_price),
            effective_price=MoneyView.of(snapshot.effective_price),
            updated_at=snapshot.updated_at,
        )


class FestivalView(BaseModel):
    """The list-page shape: enough to browse without the promotion detail."""

    id: str
    name: str
    description: str
    state: FestivalState
    starts_at: datetime
    ends_at: datetime
    game_count: int
    created_by: str
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None

    @classmethod
    def of(cls, festival: Festival) -> FestivalView:
        return cls(
            id=festival.id,
            name=festival.name,
            description=festival.description,
            state=festival.state,
            starts_at=festival.starts_at,
            ends_at=festival.ends_at,
            game_count=len(festival.games),
            created_by=festival.created_by,
            created_at=festival.created_at,
            started_at=festival.started_at,
            ended_at=festival.ended_at,
        )


class FestivalDetailView(FestivalView):
    """The detail-page shape: every selected game and what Catalog has decided
    about discounting it."""

    games: list[FestivalGameView]
    promotions: list[PromotionSnapshotView]

    @classmethod
    def of_detail(
        cls, festival: Festival, *, promotions: list[PromotionSnapshot]
    ) -> FestivalDetailView:
        by_game_active: dict[str, PromotionSnapshot] = {}
        for snap in promotions:
            if snap.is_active:
                current = by_game_active.get(snap.game_id)
                if current is None or snap.updated_at >= current.updated_at:
                    by_game_active[snap.game_id] = snap

        base = FestivalView.of(festival)
        return cls(
            **base.model_dump(),
            games=[
                FestivalGameView.of(game, active_promotion=by_game_active.get(game_id))
                for game_id, game in festival.games.items()
            ],
            promotions=[PromotionSnapshotView.of(p) for p in promotions],
        )
