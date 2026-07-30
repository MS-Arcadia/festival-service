from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from itertools import count

from app.domain.catalog_sync import CatalogGameSnapshot, PromotionSnapshot
from app.domain.festival import Festival, FestivalState
from app.platform import errors


class FixedClock:
    """Time that only moves when a test moves it."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 7, 27, 12, 0, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, **kwargs) -> datetime:
        self._now += timedelta(**kwargs)
        return self._now


def sequential_ids(prefix: str = "id"):
    counter = count(1)

    def make() -> str:
        return f"{prefix}-{next(counter)}"

    return make


class FakeUnitOfWork:
    """A transaction that does nothing — but insists on existing.

    The in-memory repositories mutate dictionaries, so there is nothing to
    commit. What this does provide is the *requirement* that a scope is open,
    which the real repositories have because they take their session from a
    context variable.
    """

    def __init__(self) -> None:
        self.depth = 0
        self.commits = 0
        self.reads = 0

    @property
    def active(self) -> bool:
        return self.depth > 0

    @asynccontextmanager
    async def begin(self):
        self.depth += 1
        try:
            yield None
        finally:
            self.depth -= 1
            if self.depth == 0:
                self.commits += 1

    @asynccontextmanager
    async def read(self):
        """A read scope. Nested inside begin(), it reuses it, like the real one."""
        self.depth += 1
        if self.depth == 1:
            self.reads += 1
        try:
            yield None
        finally:
            self.depth -= 1


def _require_scope(uow) -> None:
    if uow is not None and not uow.active:
        raise errors.internal(
            "no database session is active; repository calls must happen inside "
            "uow.begin() or uow.read()"
        )


class FakeFestivalRepository:
    def __init__(self, uow: FakeUnitOfWork | None = None) -> None:
        self.festivals: dict[str, Festival] = {}
        self._uow = uow

    async def add(self, festival: Festival) -> None:
        _require_scope(self._uow)
        if festival.id in self.festivals:
            raise errors.already_exists(f"festival {festival.id} already exists")
        self.festivals[festival.id] = festival

    async def get(self, festival_id: str) -> Festival | None:
        _require_scope(self._uow)
        return self.festivals.get(festival_id)

    async def get_for_update(self, festival_id: str) -> Festival | None:
        _require_scope(self._uow)
        return self.festivals.get(festival_id)

    async def save(self, festival: Festival) -> None:
        _require_scope(self._uow)
        if festival.id not in self.festivals:
            raise errors.not_found(f"festival {festival.id} was not found")
        festival.version += 1
        self.festivals[festival.id] = festival

    async def list(
        self, *, limit: int, offset: int, state: FestivalState | None = None
    ) -> tuple[list[Festival], int]:
        _require_scope(self._uow)
        items = list(self.festivals.values())
        if state is not None:
            items = [f for f in items if f.state is state]
        items.sort(key=lambda f: f.starts_at, reverse=True)
        return items[offset : offset + limit], len(items)

    async def find_by_game(self, game_id: str) -> list[Festival]:
        _require_scope(self._uow)
        return [
            f
            for f in self.festivals.values()
            if game_id in f.games and f.state in (FestivalState.DRAFT, FestivalState.ACTIVE)
        ]


class FakeCatalogGameRepository:
    def __init__(self, uow: FakeUnitOfWork | None = None) -> None:
        self.games: dict[str, CatalogGameSnapshot] = {}
        self._uow = uow

    async def upsert(self, snapshot: CatalogGameSnapshot) -> None:
        _require_scope(self._uow)
        self.games[snapshot.game_id] = snapshot

    async def get(self, game_id: str) -> CatalogGameSnapshot | None:
        _require_scope(self._uow)
        return self.games.get(game_id)


class FakePromotionRepository:
    def __init__(self, uow: FakeUnitOfWork | None = None) -> None:
        self.promotions: dict[str, PromotionSnapshot] = {}
        self._uow = uow

    async def upsert(self, snapshot: PromotionSnapshot) -> None:
        _require_scope(self._uow)
        self.promotions[snapshot.promotion_id] = snapshot

    async def get(self, promotion_id: str) -> PromotionSnapshot | None:
        _require_scope(self._uow)
        return self.promotions.get(promotion_id)

    async def list_for_festival(self, festival_id: str) -> list[PromotionSnapshot]:
        _require_scope(self._uow)
        return [p for p in self.promotions.values() if p.festival_id == festival_id]


class RecordingPublisher:
    """Captures what would have been published.

    Tests assert on events as much as on state: ``DiscountApplied`` firing (or
    not) is the entire observable point of consuming a promotion event, not a
    side effect of it.
    """

    def __init__(self) -> None:
        self.events: list[dict] = []

    async def enqueue(
        self,
        session,
        *,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        payload: dict,
        topic: str = "",
        causation_id: str = "",
    ) -> None:
        self.events.append(
            {
                "event_type": event_type,
                "aggregate_type": aggregate_type,
                "aggregate_id": aggregate_id,
                "payload": payload,
                "topic": topic,
                "causation_id": causation_id,
            }
        )

    def types(self) -> list[str]:
        return [e["event_type"] for e in self.events]

    def last(self, event_type: str) -> dict:
        for event in reversed(self.events):
            if event["event_type"] == event_type:
                return event
        raise AssertionError(f"no {event_type} was published; got {self.types()}")

    def count(self, event_type: str) -> int:
        return sum(1 for e in self.events if e["event_type"] == event_type)


class FakeUserDirectory:
    """Stands in for auth-profile-service's `/v1/admin/users/ids`."""

    def __init__(self, user_ids: list[str] | None = None) -> None:
        self.user_ids = list(user_ids) if user_ids is not None else ["user-1", "user-2"]
        self.calls = 0

    async def active_user_ids(self) -> list[str]:
        self.calls += 1
        return self.user_ids
