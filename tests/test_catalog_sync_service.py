from __future__ import annotations

from datetime import timedelta

import pytest

from app.application import events as ev
from app.application.catalog_sync_service import CatalogSyncService
from app.application.dto import AddGameRequest, CreateFestivalRequest
from app.application.events import DISCOUNT_APPLIED
from app.application.festival_service import FestivalService
from tests.fakes import (
    FakeCatalogGameRepository,
    FakeFestivalRepository,
    FakePromotionRepository,
    FakeUnitOfWork,
    FixedClock,
    RecordingPublisher,
    sequential_ids,
)


def promotion_payload(*, festival_id: str, game_id: str, state: str, promotion_id="promo-1"):
    return {
        "promotion_id": promotion_id,
        "festival_id": festival_id,
        "game_id": game_id,
        "state": state,
        "discount_bps": 2500,
        "starts_at": "2026-08-01T00:00:00+00:00",
        "ends_at": "2026-08-08T00:00:00+00:00",
        "list_price": {"amount_minor": "10000", "currency": "IRR"},
        "effective_price": {"amount_minor": "7500", "currency": "IRR"},
    }


@pytest.fixture
def harness():
    uow = FakeUnitOfWork()
    festivals = FakeFestivalRepository(uow)
    catalog_games = FakeCatalogGameRepository(uow)
    promotions = FakePromotionRepository(uow)
    publisher = RecordingPublisher()
    clock = FixedClock()

    festival_service = FestivalService(
        uow=uow,
        festivals=festivals,
        catalog_games=catalog_games,
        promotions=promotions,
        publisher=publisher,
        clock=clock,
        new_id=sequential_ids("fest"),
    )
    sync = CatalogSyncService(
        uow=uow,
        festivals=festivals,
        catalog_games=catalog_games,
        promotions=promotions,
        publisher=publisher,
        clock=clock,
    )
    return festival_service, sync, catalog_games, publisher, clock, uow


async def _festival_with_game(festival_service, sync, clock, game_id="game-1"):
    detail = await festival_service.create(
        admin_id="admin-1",
        request=CreateFestivalRequest(
            name="Summer Sale",
            description="",
            starts_at=clock.now() + timedelta(days=1),
            ends_at=clock.now() + timedelta(days=8),
        ),
    )
    await sync.game_published({"game_id": game_id, "title": "Star Fox", "developer_id": "dev-1"})
    return await festival_service.add_game(
        festival_id=detail.id, admin_id="admin-1", request=AddGameRequest(game_id=game_id)
    )


async def test_game_published_makes_a_game_addable(harness):
    _festival_service, sync, catalog_games, _, _clock, uow = harness
    await sync.game_published({"game_id": "game-1", "title": "Star Fox", "developer_id": "dev-1"})
    async with uow.read():
        snapshot = await catalog_games.get("game-1")
    assert snapshot.published is True
    assert snapshot.title == "Star Fox"


async def test_game_withdrawn_keeps_the_title_but_unpublishes(harness):
    _, sync, catalog_games, _, _, uow = harness
    await sync.game_published({"game_id": "game-1", "title": "Star Fox", "developer_id": "dev-1"})
    await sync.game_withdrawn({"game_id": "game-1"})
    async with uow.read():
        snapshot = await catalog_games.get("game-1")
    assert snapshot.published is False
    assert snapshot.title == "Star Fox"


async def test_promotion_approved_for_a_selected_game_fires_discount_applied(harness):
    festival_service, sync, _catalog_games, publisher, clock, _ = harness
    detail = await _festival_with_game(festival_service, sync, clock)

    await sync.promotion_event(
        ev.CATALOG_PROMOTION_APPROVED,
        promotion_payload(festival_id=detail.id, game_id="game-1", state="ACTIVE"),
    )

    applied = publisher.last(DISCOUNT_APPLIED)
    assert applied["payload"]["festival_id"] == detail.id
    assert applied["payload"]["game_id"] == "game-1"
    assert applied["payload"]["discount_bps"] == 2500


async def test_promotion_proposed_does_not_fire_discount_applied(harness):
    """Proposed is not approved. Support proposing a discount is not the same as
    the developer having agreed to it, and only the second is a real price
    change."""
    festival_service, sync, _catalog_games, publisher, clock, _ = harness
    detail = await _festival_with_game(festival_service, sync, clock)

    await sync.promotion_event(
        ev.CATALOG_PROMOTION_PROPOSED,
        promotion_payload(festival_id=detail.id, game_id="game-1", state="PENDING"),
    )

    assert publisher.count(DISCOUNT_APPLIED) == 0


async def test_a_promotion_for_a_game_not_in_this_festival_is_ignored(harness):
    """The game exists in Catalog's read-model but was never selected into this
    festival — a stray promotion naming this festival_id must not be announced as
    if it were."""
    festival_service, sync, _catalog_games, publisher, clock, _ = harness
    detail = await _festival_with_game(festival_service, sync, clock, game_id="game-1")

    await sync.promotion_event(
        ev.CATALOG_PROMOTION_APPROVED,
        promotion_payload(festival_id=detail.id, game_id="game-2", state="ACTIVE"),
    )

    assert publisher.count(DISCOUNT_APPLIED) == 0


async def test_a_promotion_with_no_festival_id_is_recorded_nowhere(harness):
    """Support can discount a game outside any festival. That is not this
    service's business."""
    _, sync, _, publisher, _, _ = harness
    await sync.promotion_event(
        ev.CATALOG_PROMOTION_APPROVED,
        promotion_payload(festival_id="", game_id="game-1", state="ACTIVE"),
    )
    assert publisher.count(DISCOUNT_APPLIED) == 0


async def test_redelivery_of_the_same_promotion_event_is_a_no_op(harness):
    """Kafka delivers at least once. A duplicate PromotionApproved must not
    double-announce the same discount."""
    festival_service, sync, _catalog_games, publisher, clock, _ = harness
    detail = await _festival_with_game(festival_service, sync, clock)

    payload = promotion_payload(festival_id=detail.id, game_id="game-1", state="ACTIVE")
    await sync.promotion_event(ev.CATALOG_PROMOTION_APPROVED, payload)
    await sync.promotion_event(ev.CATALOG_PROMOTION_APPROVED, payload)

    # The second delivery finds the promotion already ACTIVE on file and does not
    # re-announce it.
    assert publisher.count(DISCOUNT_APPLIED) == 1
