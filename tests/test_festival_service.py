from __future__ import annotations

from datetime import timedelta

import pytest

from app.application.dto import AddGameRequest, CreateFestivalRequest
from app.application.events import (
    FESTIVAL_CANCELLED,
    FESTIVAL_CREATED,
    FESTIVAL_ENDED,
    FESTIVAL_GAME_ADDED,
    FESTIVAL_STARTED,
)
from app.application.festival_service import FestivalService
from app.domain.catalog_sync import CatalogGameSnapshot
from app.domain.festival import FestivalState
from app.platform import errors
from tests.fakes import (
    FakeCatalogGameRepository,
    FakeFestivalRepository,
    FakePromotionRepository,
    FakeUnitOfWork,
    FixedClock,
    RecordingPublisher,
    sequential_ids,
)


@pytest.fixture
def harness():
    uow = FakeUnitOfWork()
    festivals = FakeFestivalRepository(uow)
    catalog_games = FakeCatalogGameRepository(uow)
    promotions = FakePromotionRepository(uow)
    publisher = RecordingPublisher()
    clock = FixedClock()
    service = FestivalService(
        uow=uow,
        festivals=festivals,
        catalog_games=catalog_games,
        promotions=promotions,
        publisher=publisher,
        clock=clock,
        new_id=sequential_ids("fest"),
    )
    return service, festivals, catalog_games, publisher, clock, uow


async def _create(service, clock, **overrides):
    defaults = {
        "name": "Summer Sale",
        "description": "",
        "starts_at": clock.now() + timedelta(days=1),
        "ends_at": clock.now() + timedelta(days=8),
    }
    defaults.update(overrides)
    return await service.create(admin_id="admin-1", request=CreateFestivalRequest(**defaults))


async def _seed_game(catalog_games, uow, clock, **overrides) -> None:
    defaults = {
        "game_id": "game-1",
        "title": "Star Fox",
        "developer_id": "dev-1",
        "published": True,
    }
    defaults.update(overrides)
    async with uow.begin():
        await catalog_games.upsert(CatalogGameSnapshot(updated_at=clock.now(), **defaults))


async def test_creating_a_festival_publishes_festival_created(harness):
    service, _, _, publisher, clock, _ = harness
    detail = await _create(service, clock)
    assert detail.state == "DRAFT"
    assert publisher.count(FESTIVAL_CREATED) == 1


async def test_adding_a_game_requires_it_to_be_known_to_this_service(harness):
    service, _, _, _, clock, _ = harness
    detail = await _create(service, clock)
    with pytest.raises(errors.AppError) as exc:
        await service.add_game(
            festival_id=detail.id, admin_id="admin-1", request=AddGameRequest(game_id="ghost")
        )
    assert exc.value.reason == "GAME_UNKNOWN"


async def test_an_unpublished_game_cannot_be_added(harness):
    service, _, catalog_games, _, clock, uow = harness
    detail = await _create(service, clock)
    await _seed_game(catalog_games, uow, clock, published=False)
    with pytest.raises(errors.AppError) as exc:
        await service.add_game(
            festival_id=detail.id, admin_id="admin-1", request=AddGameRequest(game_id="game-1")
        )
    assert exc.value.reason == "GAME_NOT_PUBLISHED"


async def test_a_published_game_can_be_added_and_the_event_carries_its_title(harness):
    service, _, catalog_games, publisher, clock, uow = harness
    detail = await _create(service, clock)
    await _seed_game(catalog_games, uow, clock)
    detail = await service.add_game(
        festival_id=detail.id, admin_id="admin-1", request=AddGameRequest(game_id="game-1")
    )
    assert detail.games[0].title == "Star Fox"
    added = publisher.last(FESTIVAL_GAME_ADDED)
    assert added["payload"]["game_id"] == "game-1"


async def test_starting_publishes_festival_started_with_the_audience_hook_empty(harness):
    """Notification's translator already reads ``audience``; this pins the empty
    default until something upstream can populate it."""
    service, _, catalog_games, publisher, clock, uow = harness
    detail = await _create(service, clock)
    await _seed_game(catalog_games, uow, clock)
    await service.add_game(
        festival_id=detail.id, admin_id="admin-1", request=AddGameRequest(game_id="game-1")
    )
    clock.advance(days=1)
    detail = await service.start(festival_id=detail.id, admin_id="admin-1")
    assert detail.state == "ACTIVE"
    started = publisher.last(FESTIVAL_STARTED)
    assert started["payload"]["audience"] == []
    assert started["payload"]["game_ids"] == ["game-1"]


async def test_a_festival_with_no_games_refuses_to_start(harness):
    service, _, _, _, clock, _ = harness
    detail = await _create(service, clock)
    with pytest.raises(errors.AppError) as exc:
        await service.start(festival_id=detail.id, admin_id="admin-1")
    assert exc.value.reason == "FESTIVAL_HAS_NO_GAMES"


async def test_ending_a_festival_publishes_festival_ended(harness):
    service, _, catalog_games, publisher, clock, uow = harness
    detail = await _create(service, clock)
    await _seed_game(catalog_games, uow, clock)
    await service.add_game(
        festival_id=detail.id, admin_id="admin-1", request=AddGameRequest(game_id="game-1")
    )
    await service.start(festival_id=detail.id, admin_id="admin-1")
    detail = await service.end(festival_id=detail.id, admin_id="admin-1")
    assert detail.state == "ENDED"
    assert publisher.count(FESTIVAL_ENDED) == 1


async def test_cancelling_a_draft_festival_publishes_festival_cancelled(harness):
    service, _, _, publisher, clock, _ = harness
    detail = await _create(service, clock)
    detail = await service.cancel(festival_id=detail.id, admin_id="admin-1")
    assert detail.state == "CANCELLED"
    assert publisher.count(FESTIVAL_CANCELLED) == 1


async def test_listing_can_be_filtered_by_state(harness):
    service, _, _, _, clock, _ = harness
    await _create(service, clock, name="A")
    cancelled = await _create(service, clock, name="B")
    await service.cancel(festival_id=cancelled.id, admin_id="admin-1")

    page = await service.list(limit=10, offset=0, state=FestivalState.CANCELLED)
    assert page.total == 1
    assert page.items[0].name == "B"
