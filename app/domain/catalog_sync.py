from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.platform.money import Money


@dataclass(slots=True)
class CatalogGameSnapshot:
    """This service's copy of one fact from Catalog: is this game on sale, and
    what is it called."""

    game_id: str
    title: str
    developer_id: str
    published: bool
    updated_at: datetime


@dataclass(slots=True)
class PromotionSnapshot:
    """This service's copy of one promotion Catalog is tracking against a festival.

    Keyed by ``promotion_id`` rather than ``game_id``: Catalog allows a new
    promotion to be proposed once an old one has been decided, and keeping the
    history rather than overwriting it is what lets a festival's page show a
    discount that was proposed and then rejected, instead of silently forgetting
    it happened.
    """

    promotion_id: str
    festival_id: str
    game_id: str
    state: str
    discount_bps: int
    starts_at: datetime
    ends_at: datetime
    list_price: Money | None
    effective_price: Money | None
    updated_at: datetime

    @property
    def is_active(self) -> bool:
        return self.state == "ACTIVE"
