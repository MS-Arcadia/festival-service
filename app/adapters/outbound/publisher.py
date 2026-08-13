"""Publishes by writing to the outbox, inside the caller's transaction.

Copied from catalog-service's adapter almost verbatim — there is exactly one
routing decision to make (which topic), and for this service it never varies:
every event this service produces goes on ``festival-events``.
"""

from __future__ import annotations

from typing import Any

from app.platform import outbox
from app.platform.events import EnvelopeFactory
from app.platform.logging import correlation_id_var


class OutboxEventPublisher:
    def __init__(self, config) -> None:
        self._topic = config.topic_festival_events
        self._factory = EnvelopeFactory(config.service_name)

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
        envelope = self._factory.build(
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload=payload,
            # Carried onward so one festival's log lines join up across every service it
            # touches, the same way catalog-service does it.
            correlation_id=correlation_id_var.get(),
            trace_id=correlation_id_var.get(),
            causation_id=causation_id,
        )
        await outbox.enqueue(session, topic=topic or self._topic, envelope=envelope)
