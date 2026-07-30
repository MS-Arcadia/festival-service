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
