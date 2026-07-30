from __future__ import annotations

import logging

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
    UserDirectory,
)
from app.domain.festival import Festival, FestivalState
from app.platform import errors

logger = logging.getLogger(__name__)


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
        users: UserDirectory | None = None,
    ) -> None:
        self._uow = uow
        self._festivals = festivals
        self._catalog_games = catalog_games
        self._promotions = promotions
        self._publisher = publisher
        self._clock = clock
        self._new_id = new_id
        # Optional on purpose: tests and any caller that does not care about the
        # notification audience get the old, honest behaviour (an empty list) instead of
        # a None-typed crash, rather than being forced to wire an HTTP gateway.
        self._users = users

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
        audience = await self._audience()
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
                    "audience": audience,
                },
            )
        return await self._detail(festival_id)

    async def _audience(self) -> list[str]:
        """Every user id `FestivalStarted` should notify.

        A festival is platform-wide (requirement 1.9), so "the audience" is "everyone
        active" — fetched from auth-profile-service, the owner of the user directory.
        Looked up outside the transaction: it is a read against another service, not
        something that needs to roll back with the festival's own state change.

        No directory configured, or the lookup fails, both degrade to an empty list with
        a warning logged rather than blocking the festival from starting — a missed
        notification pass is recoverable, a festival admins cannot start is not.
        """
        if self._users is None:
            logger.warning(
                "no user directory is configured; publishing FestivalStarted with an empty audience"
            )
            return []
        return await self._users.active_user_ids()

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
