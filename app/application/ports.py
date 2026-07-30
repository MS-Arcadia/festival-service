from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from app.domain.catalog_sync import CatalogGameSnapshot, PromotionSnapshot
from app.domain.festival import Festival, FestivalState


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdFactory(Protocol):
    def __call__(self) -> str: ...


class FestivalRepository(Protocol):
    async def add(self, festival: Festival) -> None: ...

    async def get(self, festival_id: str) -> Festival | None: ...

    async def get_for_update(self, festival_id: str) -> Festival | None:
        """Load with a row lock, for a read-modify-write.

        Admin adding a game while another request starts the same festival must
        not interleave and lose one of the two changes.
        """
        ...

    async def save(self, festival: Festival) -> None: ...

    async def list(
        self, *, limit: int, offset: int, state: FestivalState | None = None
    ) -> tuple[list[Festival], int]: ...

    async def find_by_game(self, game_id: str) -> list[Festival]:
        """Every non-terminal festival a game is currently selected into.

        What lets a ``PromotionApproved`` event be checked against "is this
        actually one of ours" without scanning every festival on the platform.
        """
        ...


class CatalogGameRepository(Protocol):
    """The read-model built from ``game-events``."""

    async def upsert(self, snapshot: CatalogGameSnapshot) -> None: ...

    async def get(self, game_id: str) -> CatalogGameSnapshot | None: ...


class PromotionRepository(Protocol):
    """The read-model of Catalog's promotions, scoped to this platform's festivals."""

    async def upsert(self, snapshot: PromotionSnapshot) -> None: ...

    async def get(self, promotion_id: str) -> PromotionSnapshot | None: ...

    async def list_for_festival(self, festival_id: str) -> list[PromotionSnapshot]: ...


class UserDirectory(Protocol):
    """The platform's user directory, for events that are meant for everyone.

    A festival going ACTIVE is platform-wide (requirement 1.9) — every user is the
    audience, not a subscriber list this service owns. Getting "everyone" means asking
    the service that owns the user directory, auth-profile-service, rather than this
    service trying to keep its own copy of every account on the platform.
    """

    async def active_user_ids(self) -> list[str]:
        """Every currently-active user id, for a platform-wide broadcast.

        Failure here must never block a festival from starting: it degrades to
        `FestivalService` publishing an empty audience and logging a warning, since a
        missed notification pass is recoverable and a stuck festival is not.
        """
        ...


class EventPublisher(Protocol):
    """Appends an event to the outbox inside the caller's transaction.

    Not "publishes" — nothing here talks to Kafka directly. The send happens
    later, from the dispatcher, after the transaction that produced the event has
    committed.
    """

    async def enqueue(
        self,
        session: Any,
        *,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        payload: dict[str, Any],
        topic: str = "",
        causation_id: str = "",
    ) -> None: ...
