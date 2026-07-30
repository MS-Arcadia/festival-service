"""PostgreSQL repositories.

Each one implements a protocol from ``app/application/ports.py`` and does two
jobs: run the query, and translate between rows and domain objects. The session
comes from ``platform.db.current_session``, which the unit of work sets for the
duration of a transaction.
"""

from __future__ import annotations

from sqlalchemy import select

from app.adapters.outbound.models import (
    CatalogGameRow,
    FestivalGameRow,
    FestivalRow,
    PromotionSnapshotRow,
)
from app.domain.catalog_sync import CatalogGameSnapshot, PromotionSnapshot
from app.domain.festival import Festival, FestivalGame, FestivalState
from app.platform import errors
from app.platform.db import current_session
from app.platform.money import Money

# --- mapping ---------------------------------------------------------------


def _money(minor: int | None, currency: str | None) -> Money | None:
    if minor is None or not currency:
        return None
    return Money(minor, currency)


def _to_festival(row: FestivalRow) -> Festival:
    return Festival(
        id=row.id,
        name=row.name,
        description=row.description,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        state=FestivalState(row.state),
        created_by=row.created_by,
        created_at=row.created_at,
        started_at=row.started_at,
        ended_at=row.ended_at,
        games={
            g.game_id: FestivalGame(
                game_id=g.game_id,
                title=g.title,
                developer_id=g.developer_id,
                added_by=g.added_by,
                added_at=g.added_at,
            )
            for g in row.games
        },
        version=row.version,
    )


def _to_catalog_game(row: CatalogGameRow) -> CatalogGameSnapshot:
    return CatalogGameSnapshot(
        game_id=row.game_id,
        title=row.title,
        developer_id=row.developer_id,
        published=row.published,
        updated_at=row.updated_at,
    )


def _to_promotion(row: PromotionSnapshotRow) -> PromotionSnapshot:
    return PromotionSnapshot(
        promotion_id=row.promotion_id,
        festival_id=row.festival_id,
        game_id=row.game_id,
        state=row.state,
        discount_bps=row.discount_bps,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        list_price=_money(row.list_price_minor, row.list_price_currency),
        effective_price=_money(row.effective_price_minor, row.effective_price_currency),
        updated_at=row.updated_at,
    )


# --- repositories ------------------------------------------------------------


class PostgresFestivalRepository:
    async def add(self, festival: Festival) -> None:
        session = current_session()
        session.add(
            FestivalRow(
                id=festival.id,
                name=festival.name,
                description=festival.description,
                state=str(festival.state),
                starts_at=festival.starts_at,
                ends_at=festival.ends_at,
                created_by=festival.created_by,
                created_at=festival.created_at,
            )
        )
        await session.flush()

    async def get(self, festival_id: str) -> Festival | None:
        session = current_session()
        row = await session.get(FestivalRow, festival_id)
        return _to_festival(row) if row is not None else None

    async def get_for_update(self, festival_id: str) -> Festival | None:
        session = current_session()
        row = (
            await session.execute(
                select(FestivalRow).where(FestivalRow.id == festival_id).with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        # The lock is on the festival row only; the games are loaded after it is
        # held, so nothing can add or remove one between the lock and the read.
        await session.refresh(row, ["games"])
        return _to_festival(row)

    async def save(self, festival: Festival) -> None:
        """Write the aggregate back, its games included.

        The game list is replaced rather than diffed — it is at most a few dozen
        rows, and a diff here would be code whose only purpose is avoiding writes
        that cost nothing.
        """
        session = current_session()
        row = await session.get(FestivalRow, festival.id)
        if row is None:
            raise errors.not_found(f"festival {festival.id} was not found")

        if row.version != festival.version:
            raise errors.conflict(
                f"festival {festival.id} was modified by another request; retry",
                reason="CONCURRENT_MODIFICATION",
            )

        row.name = festival.name
        row.description = festival.description
        row.state = str(festival.state)
        row.starts_at = festival.starts_at
        row.ends_at = festival.ends_at
        row.started_at = festival.started_at
        row.ended_at = festival.ended_at
        row.version = festival.version + 1
        festival.version = row.version

        existing = {g.game_id: g for g in row.games}
        wanted = festival.games
        for game_id in list(existing):
            if game_id not in wanted:
                row.games.remove(existing[game_id])
        for game_id, game in wanted.items():
            if game_id not in existing:
                row.games.append(
                    FestivalGameRow(
                        festival_id=festival.id,
                        game_id=game.game_id,
                        title=game.title,
                        developer_id=game.developer_id,
                        added_by=game.added_by,
                        added_at=game.added_at,
                    )
                )
        await session.flush()

    async def list(
        self, *, limit: int, offset: int, state: FestivalState | None = None
    ) -> tuple[list[Festival], int]:
        session = current_session()
        stmt = select(FestivalRow)
        if state is not None:
            stmt = stmt.where(FestivalRow.state == str(state))
        stmt = stmt.order_by(FestivalRow.starts_at.desc(), FestivalRow.id)

        total = len((await session.execute(stmt)).scalars().all())
        rows = (await session.execute(stmt.limit(limit).offset(offset))).scalars().all()
        return [_to_festival(r) for r in rows], total

    async def find_by_game(self, game_id: str) -> list[Festival]:
        session = current_session()
        stmt = (
            select(FestivalRow)
            .join(FestivalGameRow, FestivalGameRow.festival_id == FestivalRow.id)
            .where(
                FestivalGameRow.game_id == game_id,
                FestivalRow.state.in_([str(FestivalState.DRAFT), str(FestivalState.ACTIVE)]),
            )
        )
        rows = (await session.execute(stmt)).scalars().all()
        return [_to_festival(r) for r in rows]


class PostgresCatalogGameRepository:
    async def upsert(self, snapshot: CatalogGameSnapshot) -> None:
        session = current_session()
        row = await session.get(CatalogGameRow, snapshot.game_id)
        if row is None:
            session.add(
                CatalogGameRow(
                    game_id=snapshot.game_id,
                    title=snapshot.title,
                    developer_id=snapshot.developer_id,
                    published=snapshot.published,
                    updated_at=snapshot.updated_at,
                )
            )
        else:
            row.title = snapshot.title or row.title
            row.developer_id = snapshot.developer_id or row.developer_id
            row.published = snapshot.published
            row.updated_at = snapshot.updated_at
        await session.flush()

    async def get(self, game_id: str) -> CatalogGameSnapshot | None:
        session = current_session()
        row = await session.get(CatalogGameRow, game_id)
        return _to_catalog_game(row) if row is not None else None


class PostgresPromotionRepository:
    async def upsert(self, snapshot: PromotionSnapshot) -> None:
        session = current_session()
        row = await session.get(PromotionSnapshotRow, snapshot.promotion_id)
        if row is None:
            session.add(
                PromotionSnapshotRow(
                    promotion_id=snapshot.promotion_id,
                    festival_id=snapshot.festival_id,
                    game_id=snapshot.game_id,
                    state=snapshot.state,
                    discount_bps=snapshot.discount_bps,
                    starts_at=snapshot.starts_at,
                    ends_at=snapshot.ends_at,
                    list_price_minor=snapshot.list_price.minor if snapshot.list_price else None,
                    list_price_currency=(
                        snapshot.list_price.currency if snapshot.list_price else None
                    ),
                    effective_price_minor=(
                        snapshot.effective_price.minor if snapshot.effective_price else None
                    ),
                    effective_price_currency=(
                        snapshot.effective_price.currency if snapshot.effective_price else None
                    ),
                    updated_at=snapshot.updated_at,
                )
            )
        else:
            row.state = snapshot.state
            row.discount_bps = snapshot.discount_bps
            row.starts_at = snapshot.starts_at
            row.ends_at = snapshot.ends_at
            row.list_price_minor = snapshot.list_price.minor if snapshot.list_price else None
            row.list_price_currency = snapshot.list_price.currency if snapshot.list_price else None
            row.effective_price_minor = (
                snapshot.effective_price.minor if snapshot.effective_price else None
            )
            row.effective_price_currency = (
                snapshot.effective_price.currency if snapshot.effective_price else None
            )
            row.updated_at = snapshot.updated_at
        await session.flush()

    async def get(self, promotion_id: str) -> PromotionSnapshot | None:
        session = current_session()
        row = await session.get(PromotionSnapshotRow, promotion_id)
        return _to_promotion(row) if row is not None else None

    async def list_for_festival(self, festival_id: str) -> list[PromotionSnapshot]:
        session = current_session()
        stmt = (
            select(PromotionSnapshotRow)
            .where(PromotionSnapshotRow.festival_id == festival_id)
            .order_by(PromotionSnapshotRow.updated_at.desc())
        )
        rows = (await session.execute(stmt)).scalars().all()
        return [_to_promotion(r) for r in rows]
