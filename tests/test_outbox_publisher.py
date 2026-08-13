"""The real publisher, not the fake one.

Every other test in this suite uses ``RecordingPublisher``, which is the right thing for
asserting *which* events a use case emits. The cost is that the adapter that actually
builds them was never executed once: it called ``Envelope.new(source=...)``, a constructor
that does not exist on a dataclass whose field is ``producer``, and every attempt to create
a festival answered 500 with a green test suite behind it.

So this exercises the adapter itself. The session is a stand-in — the point is the envelope
that reaches the outbox, not the database write, which ``outbox.enqueue`` is responsible for
and tested for elsewhere.
"""

from __future__ import annotations

import pytest

from app.adapters.outbound.publisher import OutboxEventPublisher
from app.platform import outbox


class Config:
    topic_festival_events = "festival-events"
    service_name = "festival-service"


class CapturingSession:
    """Records what would have been added, so no database is needed to see the envelope."""

    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, instance: object) -> None:
        self.added.append(instance)


@pytest.mark.asyncio
async def test_the_publisher_builds_an_envelope_the_outbox_accepts():
    session = CapturingSession()

    await OutboxEventPublisher(Config()).enqueue(
        session,
        event_type="FestivalCreated",
        aggregate_type="Festival",
        aggregate_id="fest-1",
        payload={"name": "Winter Arcade"},
    )

    assert len(session.added) == 1
    message = session.added[0]
    assert message.topic == "festival-events"
    assert message.event_type == "FestivalCreated"
    assert message.partition_key == "fest-1"

    envelope = message.envelope
    assert envelope["event_type"] == "FestivalCreated"
    assert envelope["payload"] == {"name": "Winter Arcade"}
    # The producer is what every consumer reads to know where an event came from, and it is
    # the field the broken call passed as `source`.
    assert envelope["producer"] == "festival-service"
    assert envelope["event_id"]


@pytest.mark.asyncio
async def test_an_explicit_topic_wins_over_the_default():
    session = CapturingSession()

    await OutboxEventPublisher(Config()).enqueue(
        session,
        event_type="FestivalEnded",
        aggregate_type="Festival",
        aggregate_id="fest-2",
        payload={},
        topic="somewhere-else",
    )

    assert session.added[0].topic == "somewhere-else"


@pytest.mark.asyncio
async def test_the_correlation_id_travels_with_the_event():
    """One festival's log lines have to join up across the services the event reaches."""
    from app.platform.logging import correlation_id_var

    token = correlation_id_var.set("corr-123")
    try:
        session = CapturingSession()
        await OutboxEventPublisher(Config()).enqueue(
            session,
            event_type="FestivalStarted",
            aggregate_type="Festival",
            aggregate_id="fest-3",
            payload={},
        )
    finally:
        correlation_id_var.reset(token)

    assert session.added[0].envelope["correlation_id"] == "corr-123"


def test_the_outbox_is_the_only_way_out():
    """A publisher that opened its own session could write an event for a festival that was
    never saved. It takes the caller's session, so the two cannot come apart."""
    assert "session" in outbox.enqueue.__code__.co_varnames
