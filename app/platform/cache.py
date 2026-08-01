"""A Redis-backed cache-aside helper for expensive, public, read-heavy queries.

Deliberately simple: get-or-compute with a short TTL, no invalidation on write. A
stale catalogue page for up to `ttl` seconds is an acceptable trade for cutting a
repeated read to zero database round trips — this is a read-side optimisation for
requirement 2.3's p95 target, never the source of truth for money. The purchase
saga re-reads a game's price synchronously through its own Anti-Corruption Layer
before charging anyone (see order-service's `adapters/outbound/catalog.py`), so a
cache page a few seconds stale never gets a chance to sell at the wrong price.

Fails open: a Redis outage falls straight back to computing the answer, logged
once and never raised — a cache is an optimisation, and an optional dependency
that can take the platform down is not optional.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)


class Cache:
    def __init__(self, client: Any | None, *, prefix: str, default_ttl: int) -> None:
        self._client = client
        self._prefix = prefix
        self._default_ttl = default_ttl

    @property
    def enabled(self) -> bool:
        return self._client is not None

    async def get_or_set(
        self,
        key: str,
        compute: Callable[[], Awaitable[Any]],
        *,
        ttl: int | None = None,
    ) -> Any:
        if self._client is None:
            return await compute()

        full_key = f"{self._prefix}:{key}"
        try:
            cached = await self._client.get(full_key)
        except Exception:
            logger.warning("cache read failed, falling back to the database", exc_info=True)
            return await compute()

        if cached is not None:
            return json.loads(cached)

        value = await compute()
        try:
            await self._client.set(
                full_key, json.dumps(value, default=str), ex=ttl or self._default_ttl
            )
        except Exception:
            logger.warning("cache write failed", exc_info=True)
        return value
