from __future__ import annotations

from app.application import events as ev
from app.application.dto import (
    AddGameRequest,
    CreateFestivalRequest,
    FestivalDetailView,
    FestivalView,
    Page,
    RescheduleFestivalRequest,
)
from app.application.ports import (
    Clock,
    EventPublisher,
    FestivalRepository,
    IdFactory,
)
from app.domain.festival import Festival, FestivalState
from app.platform import errors


class FestivalService:
    def __init__(
        self,
        *,
        uow,
        festivals: FestivalRepository,

        catalog_games,
        promotions,
        publisher: EventPublisher,
        clock: Clock,
        new_id: IdFactory,
    ) -> None:
        self._uow = uow
        self._festivals = festivals
        self._catalog_games = catalog_games
        self._promotions = promotions
        self._publisher = publisher
        self._clock = clock
        self._new_id = new_id


    async def create(self, *, admin_id: str, request: CreateFestivalRequest) -> FestivalDetailView:
        now = self._clock.now()
        festival = Festival.create(
            festival_id=self._new_id(),
            name=request.name,
            description=request.description,
            starts_at=request.starts_at,
            ends_at=request.ends_at,
            created_by=admin_id,
            now=now,
        )
        async with self._uow.begin() as session:
            await self._festivals.add(festival)
            await self._publisher.enqueue(
                session,
                event_type=ev.FESTIVAL_CREATED,
                aggregate_type=ev.AGGREGATE_FESTIVAL,
                aggregate_id=festival.id,
                payload={
                    "festival_id": festival.id,
                    "name": festival.name,
                    "starts_at": festival.starts_at.isoformat(),
                    "ends_at": festival.ends_at.isoformat(),
                    "created_by": admin_id,
                },
            )
        return await self._detail(festival.id)

    async def reschedule(
        self, *, festival_id: str, admin_id: str, request: RescheduleFestivalRequest
    ) -> FestivalDetailView:
        now = self._clock.now()
        async with self._uow.begin():
            festival = await self._load(festival_id)
            festival.reschedule(starts_at=request.starts_at, ends_at=request.ends_at, now=now)
            await self._festivals.save(festival)
        return await self._detail(festival_id)

    async def add_game(
        self, *, festival_id: str, admin_id: str, request: AddGameRequest
    ) -> FestivalDetailView:
        now = self._clock.now()
        async with self._uow.begin() as session:
            game = await self._catalog_games.get(request.game_id)
            if game is None:
                raise errors.not_found(
                    f"game {request.game_id} is not known to this service yet",
                    reason="GAME_UNKNOWN",
                )
            if not game.published:
                raise errors.failed_precondition(
                    f"game {request.game_id} is not published", reason="GAME_NOT_PUBLISHED"
                )

            festival = await self._load(festival_id)
            festival.add_game(
                game_id=game.game_id,
                title=game.title,
                developer_id=game.developer_id,
                added_by=admin_id,
                now=now,
            )
            await self._festivals.save(festival)
            await self._publisher.enqueue(
                session,
                event_type=ev.FESTIVAL_GAME_ADDED,
                aggregate_type=ev.AGGREGATE_FESTIVAL,
                aggregate_id=festival.id,
                payload={
                    "festival_id": festival.id,
                    "game_id": game.game_id,
                    "title": game.title,
                    "developer_id": game.developer_id,
                    "added_by": admin_id,
                },
            )
        return await self._detail(festival_id)

    async def remove_game(
        self, *, festival_id: str, admin_id: str, game_id: str
    ) -> FestivalDetailView:
        async with self._uow.begin() as session:
            festival = await self._load(festival_id)
            festival.remove_game(game_id=game_id)
            await self._festivals.save(festival)
            await self._publisher.enqueue(
                session,
                event_type=ev.FESTIVAL_GAME_REMOVED,
                aggregate_type=ev.AGGREGATE_FESTIVAL,
                aggregate_id=festival.id,
                payload={
                    "festival_id": festival.id,
                    "game_id": game_id,
                    "removed_by": admin_id,
                },
            )
        return await self._detail(festival_id)


    async def start(self, *, festival_id: str, admin_id: str) -> FestivalDetailView:
        now = self._clock.now()
        async with self._uow.begin() as session:
            festival = await self._load(festival_id)
            festival.start(now=now)
            await self._festivals.save(festival)
            await self._publisher.enqueue(
                session,
                event_type=ev.FESTIVAL_STARTED,
                aggregate_type=ev.AGGREGATE_FESTIVAL,
                aggregate_id=festival.id,
                payload={
                    "festival_id": festival.id,
                    "name": festival.name,
                    "starts_at": festival.starts_at.isoformat(),
                    "ends_at": festival.ends_at.isoformat(),
                    "game_ids": list(festival.games.keys()),
                    "started_by": admin_id,
                    "audience": [],
                },
            )
        return await self._detail(festival_id)

    async def end(self, *, festival_id: str, admin_id: str) -> FestivalDetailView:
        now = self._clock.now()
        async with self._uow.begin() as session:
            festival = await self._load(festival_id)
            festival.end(now=now)
            await self._festivals.save(festival)
            await self._publisher.enqueue(
                session,
                event_type=ev.FESTIVAL_ENDED,
                aggregate_type=ev.AGGREGATE_FESTIVAL,
                aggregate_id=festival.id,
                payload={
                    "festival_id": festival.id,
                    "name": festival.name,
                    "ended_by": admin_id,
                },
            )
        return await self._detail(festival_id)

    async def cancel(self, *, festival_id: str, admin_id: str) -> FestivalDetailView:
        now = self._clock.now()
        async with self._uow.begin() as session:
            festival = await self._load(festival_id)
            festival.cancel(now=now)
            await self._festivals.save(festival)
            await self._publisher.enqueue(
                session,
                event_type=ev.FESTIVAL_CANCELLED,
                aggregate_type=ev.AGGREGATE_FESTIVAL,
                aggregate_id=festival.id,
                payload={
                    "festival_id": festival.id,
                    "name": festival.name,
                    "cancelled_by": admin_id,
                },
            )
        return await self._detail(festival_id)


    async def get(self, festival_id: str) -> FestivalDetailView:
        return await self._detail(festival_id)

    async def list(
        self, *, limit: int, offset: int, state: FestivalState | None = None
    ) -> Page[FestivalView]:
        async with self._uow.read():
            festivals, total = await self._festivals.list(limit=limit, offset=offset, state=state)
        return Page(
            items=[FestivalView.of(f) for f in festivals], total=total, limit=limit, offset=offset
        )


    async def _load(self, festival_id: str) -> Festival:
        festival = await self._festivals.get_for_update(festival_id)
        if festival is None:
            raise errors.not_found(f"festival {festival_id} was not found")
        return festival

    async def _detail(self, festival_id: str) -> FestivalDetailView:
        async with self._uow.read():
            festival = await self._festivals.get(festival_id)
            if festival is None:
                raise errors.not_found(f"festival {festival_id} was not found")
            promotions = await self._promotions.list_for_festival(festival_id)
        return FestivalDetailView.of_detail(festival, promotions=promotions)
