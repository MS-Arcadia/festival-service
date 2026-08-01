"""Festival endpoints.

Every mutating route requires ``ADMIN`` — requirement 1.9 names the platform
itself (Admin) as the one who creates a festival and chooses its games, not
Support and not a developer. Browsing is public, matching the catalogue's own
precedent: a sale nobody can see without logging in defeats the point of running
one.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from fastapi.encoders import jsonable_encoder

from app.adapters.inbound.rest.deps import CacheDep, CallerDep, FestivalServiceDep, PageDep
from app.application.dto import (
    AddGameRequest,
    CreateFestivalRequest,
    FestivalDetailView,
    FestivalView,
    Page,
    RescheduleFestivalRequest,
)
from app.domain.festival import FestivalState
from app.platform.auth import Role, require

router = APIRouter(prefix="/v1/festivals", tags=["festivals"])

admin_only = [Depends(require(Role.ADMIN))]


# --- public browsing -----------------------------------------------------


@router.get("", response_model=Page[FestivalView])
async def list_festivals(
    service: FestivalServiceDep,
    cache: CacheDep,
    page: PageDep,
    state: Annotated[FestivalState | None, Query()] = None,
) -> Page[FestivalView]:
    key = f"list:{page.limit}:{page.offset}:{state}"
    return await cache.get_or_set(
        key, lambda: _as_json(service.list(limit=page.limit, offset=page.offset, state=state))
    )


@router.get("/{festival_id}", response_model=FestivalDetailView)
async def get_festival(
    service: FestivalServiceDep, cache: CacheDep, festival_id: str
) -> FestivalDetailView:
    return await cache.get_or_set(festival_id, lambda: _as_json(service.get(festival_id)))


async def _as_json(awaitable):  # type: ignore[no-untyped-def]
    """A cache stores JSON, not a Pydantic model — this is the one place that
    makes the two agree, so every route above stays free of the distinction."""
    return jsonable_encoder(await awaitable)


# --- admin writes ----------------------------------------------------------


@router.post(
    "",
    response_model=FestivalDetailView,
    status_code=status.HTTP_201_CREATED,
    dependencies=admin_only,
)
async def create_festival(
    service: FestivalServiceDep, caller: CallerDep, request: CreateFestivalRequest
) -> FestivalDetailView:
    return await service.create(admin_id=caller.user_id, request=request)


@router.patch("/{festival_id}", response_model=FestivalDetailView, dependencies=admin_only)
async def reschedule_festival(
    service: FestivalServiceDep,
    caller: CallerDep,
    festival_id: str,
    request: RescheduleFestivalRequest,
) -> FestivalDetailView:
    return await service.reschedule(
        festival_id=festival_id, admin_id=caller.user_id, request=request
    )


@router.post(
    "/{festival_id}/games",
    response_model=FestivalDetailView,
    status_code=status.HTTP_201_CREATED,
    dependencies=admin_only,
)
async def add_game(
    service: FestivalServiceDep, caller: CallerDep, festival_id: str, request: AddGameRequest
) -> FestivalDetailView:
    return await service.add_game(festival_id=festival_id, admin_id=caller.user_id, request=request)


@router.delete(
    "/{festival_id}/games/{game_id}",
    response_model=FestivalDetailView,
    dependencies=admin_only,
)
async def remove_game(
    service: FestivalServiceDep, caller: CallerDep, festival_id: str, game_id: str
) -> FestivalDetailView:
    return await service.remove_game(
        festival_id=festival_id, admin_id=caller.user_id, game_id=game_id
    )


@router.post("/{festival_id}/start", response_model=FestivalDetailView, dependencies=admin_only)
async def start_festival(
    service: FestivalServiceDep, caller: CallerDep, festival_id: str
) -> FestivalDetailView:
    return await service.start(festival_id=festival_id, admin_id=caller.user_id)


@router.post("/{festival_id}/end", response_model=FestivalDetailView, dependencies=admin_only)
async def end_festival(
    service: FestivalServiceDep, caller: CallerDep, festival_id: str
) -> FestivalDetailView:
    return await service.end(festival_id=festival_id, admin_id=caller.user_id)


@router.post("/{festival_id}/cancel", response_model=FestivalDetailView, dependencies=admin_only)
async def cancel_festival(
    service: FestivalServiceDep, caller: CallerDep, festival_id: str
) -> FestivalDetailView:
    return await service.cancel(festival_id=festival_id, admin_id=caller.user_id)
