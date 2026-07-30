from __future__ import annotations

from datetime import UTC, datetime

from app.application import events as ev
from app.application.ports import (
    CatalogGameRepository,
    Clock,
    EventPublisher,
    FestivalRepository,
    PromotionRepository,
)
from app.domain.catalog_sync import CatalogGameSnapshot, PromotionSnapshot
from app.platform import errors
from app.platform.money import Money, MoneyError


class CatalogSyncService:
    def __init__(
        self,
        *,
        uow,
        festivals: FestivalRepository,
        catalog_games: CatalogGameRepository,
        promotions: PromotionRepository,
        publisher: EventPublisher,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._festivals = festivals
        self._catalog_games = catalog_games
        self._promotions = promotions
        self._publisher = publisher
        self._clock = clock


    async def game_published(self, payload: dict) -> None:
        game_id = _require(payload, "game_id")
        async with self._uow.begin():
            await self._catalog_games.upsert(
                CatalogGameSnapshot(
                    game_id=game_id,
                    title=str(payload.get("title") or ""),
                    developer_id=str(payload.get("developer_id") or ""),
                    published=True,
                    updated_at=self._clock.now(),
                )
            )

    async def game_withdrawn(self, payload: dict) -> None:
        game_id = _require(payload, "game_id")
        async with self._uow.begin():
            existing = await self._catalog_games.get(game_id)
            await self._catalog_games.upsert(
                CatalogGameSnapshot(
                    game_id=game_id,
                    title=existing.title if existing else "",
                    developer_id=existing.developer_id if existing else "",
                    published=False,
                    updated_at=self._clock.now(),
                )
            )

    async def game_relisted(self, payload: dict) -> None:
        game_id = _require(payload, "game_id")
        async with self._uow.begin():
            existing = await self._catalog_games.get(game_id)
            await self._catalog_games.upsert(
                CatalogGameSnapshot(
                    game_id=game_id,
                    title=existing.title if existing else "",
                    developer_id=existing.developer_id if existing else "",
                    published=True,
                    updated_at=self._clock.now(),
                )
            )

    async def game_updated(self, payload: dict) -> None:
        """A developer edited the title or description. Only the title is kept
        here — it is the only field a festival page renders."""
        game_id = _require(payload, "game_id")
        title = payload.get("title")
        if title is None:
            return
        async with self._uow.begin():
            existing = await self._catalog_games.get(game_id)
            await self._catalog_games.upsert(
                CatalogGameSnapshot(
                    game_id=game_id,
                    title=str(title),
                    developer_id=(
                        existing.developer_id
                        if existing
                        else str(payload.get("developer_id") or "")
                    ),
                    published=existing.published if existing else False,
                    updated_at=self._clock.now(),
                )
            )


    async def promotion_event(self, event_type: str, payload: dict) -> None:
        """Record what Catalog reported about a promotion.

        ``festival_id`` is optional on Catalog's side — Support can discount a
        game outside any festival — so a payload with no festival_id, or one that
        does not name a festival this service knows about, is recorded nowhere:
        it is not this service's business, and there is nothing to announce.
        """
        promotion_id = _require(payload, "promotion_id")
        festival_id = str(payload.get("festival_id") or "")
        game_id = _require(payload, "game_id")

        if not festival_id:
            return

        async with self._uow.begin() as session:
            festival = await self._festivals.get(festival_id)
            if festival is None:
                return

            previous = await self._promotions.get(promotion_id)
            was_already_active = previous is not None and previous.state == "ACTIVE"

            snapshot = PromotionSnapshot(
                promotion_id=promotion_id,
                festival_id=festival_id,
                game_id=game_id,
                state=str(payload.get("state") or ""),
                discount_bps=int(payload.get("discount_bps") or 0),
                starts_at=_parse(payload.get("starts_at")),
                ends_at=_parse(payload.get("ends_at")),
                list_price=_money(payload.get("list_price")),
                effective_price=_money(payload.get("effective_price")),
                updated_at=self._clock.now(),
            )
            await self._promotions.upsert(snapshot)

            newly_active = (
                event_type == ev.CATALOG_PROMOTION_APPROVED
                and game_id in festival.games
                and not was_already_active
            )
            if newly_active:
                await self._publisher.enqueue(
                    session,
                    event_type=ev.DISCOUNT_APPLIED,
                    aggregate_type=ev.AGGREGATE_FESTIVAL,
                    aggregate_id=festival_id,
                    payload={
                        "festival_id": festival_id,
                        "game_id": game_id,
                        "title": festival.games[game_id].title,
                        "promotion_id": promotion_id,
                        "discount_bps": snapshot.discount_bps,
                        "list_price": payload.get("list_price"),
                        "effective_price": payload.get("effective_price"),
                        "starts_at": payload.get("starts_at"),
                        "ends_at": payload.get("ends_at"),
                    },
                )


def _require(payload: dict, field: str) -> str:
    value = str(payload.get(field) or "")
    if not value:
        raise errors.invalid_argument(f"event carried no {field}", reason="MISSING_FIELD")
    return value


def _parse(value: object) -> datetime:
    if not value:
        return datetime.now(UTC)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _money(raw: object) -> Money | None:
    if not raw:
        return None
    try:
        return Money.from_wire(raw)
    except MoneyError:
        return None
