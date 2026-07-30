"""Publishes by writing to the outbox, inside the caller's transaction.

Copied from catalog-service's adapter almost verbatim — there is exactly one
routing decision to make (which topic), and for this service it never varies:
every event this service produces goes on ``festival-events``.
"""

from __future__ import annotations

from typing import Any

from app.platform import outbox
from app.platform.events import Envelope


class OutboxEventPublisher:
    def __init__(self, config) -> None:
        self._topic = config.topic_festival_events
        self._source = config.service_name

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
    ) -> None:
        envelope = Envelope.new(
            event_type=event_type,
            source=self._source,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload=payload,
            causation_id=causation_id,
        )
        await outbox.enqueue(session, topic=topic or self._topic, envelope=envelope)
