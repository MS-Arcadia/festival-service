"""The Kafka inbound adapter: this service's other half of "select games and
notice discounts", driven by Catalog's events instead of Admin's clicks.

``game-events`` is a topic shared with every other consumer of Catalog's
lifecycle (Search, Profile, Order, Notification…) and carries far more event
types than the four this service acts on — ``GameSubmitted``, ``GameApproved``
and so on are Support's and the developer's business. ``dead_letter_unknown`` is
left at its default of off, so the rest of that traffic is silently ignored
rather than treated as a contract violation and buried into a dead-letter queue
that would otherwise fill with another service's healthy events.
"""

from __future__ import annotations

import logging

from app.application import events as ev
from app.application.catalog_sync_service import CatalogSyncService
from app.platform.events import Envelope
from app.platform.kafka import Router

logger = logging.getLogger(__name__)

_PROMOTION_EVENTS = frozenset(
    {
        ev.CATALOG_PROMOTION_PROPOSED,
        ev.CATALOG_PROMOTION_APPROVED,
        ev.CATALOG_PROMOTION_REJECTED,
        ev.CATALOG_PROMOTION_CANCELLED,
    }
)


class Handlers:
    def __init__(self, catalog_sync: CatalogSyncService) -> None:
        self._catalog_sync = catalog_sync

    def game_events_router(self) -> Router:
        router = Router(dead_letter_unknown=False)
        router.on(ev.CATALOG_GAME_PUBLISHED, self.handle_game_published)
        router.on(ev.CATALOG_GAME_WITHDRAWN, self.handle_game_withdrawn)
        router.on(ev.CATALOG_GAME_RELISTED, self.handle_game_relisted)
        router.on(ev.CATALOG_GAME_UPDATED, self.handle_game_updated)
        for event_type in _PROMOTION_EVENTS:
            router.on(event_type, self._promotion_handler(event_type))
        return router

    async def handle_game_published(self, envelope: Envelope) -> None:
        await self._catalog_sync.game_published(envelope.payload)

    async def handle_game_withdrawn(self, envelope: Envelope) -> None:
        await self._catalog_sync.game_withdrawn(envelope.payload)

    async def handle_game_relisted(self, envelope: Envelope) -> None:
        await self._catalog_sync.game_relisted(envelope.payload)

    async def handle_game_updated(self, envelope: Envelope) -> None:
        await self._catalog_sync.game_updated(envelope.payload)

    def _promotion_handler(self, event_type: str):
        async def handle(envelope: Envelope) -> None:
            logger.info(
                "recording promotion update",
                extra={
                    "event_type": event_type,
                    "promotion_id": envelope.payload.get("promotion_id"),
                    "festival_id": envelope.payload.get("festival_id"),
                },
            )
            await self._catalog_sync.promotion_event(event_type, envelope.payload)

        return handle
