"""Wiring for the HTTP layer.

The service itself is built once at boot and hung on ``app.state``; this is the
accessor. Keeping it in one file means a router never reaches into the bootstrap
module, so the direction of dependency stays one-way.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Query, Request

from app.application.festival_service import FestivalService
from app.platform.auth import Principal, current_principal
from app.platform.cache import Cache


def festivals(request: Request) -> FestivalService:
    return request.app.state.festival_service


def cache(request: Request) -> Cache:
    return request.app.state.cache


class Pagination:
    """A bounded page.

    ``limit`` is capped rather than trusted. An unbounded page size is a denial
    of service one query string away — and the cap belongs at the edge, where the
    request arrives.
    """

    def __init__(
        self,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    ) -> None:
        self.limit = limit
        self.offset = offset


FestivalServiceDep = Annotated[FestivalService, Depends(festivals)]
CacheDep = Annotated[Cache, Depends(cache)]
PageDep = Annotated[Pagination, Depends(Pagination)]
CallerDep = Annotated[Principal, Depends(current_principal)]
