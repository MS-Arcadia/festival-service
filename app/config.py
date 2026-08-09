from __future__ import annotations

from functools import lru_cache

from app.platform.config import BaseConfig


class Config(BaseConfig):
    service_name: str = "festival-service"
    http_port: int = 8089

    currency: str = "IRR"

    # --- auth-profile-service (synchronous, for the FestivalStarted audience) ---
    # `FestivalStarted` is platform-wide (requirement 1.9), so this service asks
    # auth-profile-service — the owner of the user directory — for every active user id
    # when a festival starts. See app/adapters/outbound/auth_profile.py.
    auth_profile_base_url: str = "http://localhost:8085"
    auth_profile_timeout_seconds: float = 3.0

    # --- kafka topics ---
    topic_game_events: str = "game-events"
    topic_festival_events: str = "festival-events"
    consumer_group: str = "festival-service"

    @property
    def owned_topics(self) -> list[str]:
        # A service creates every topic it produces to, plus the dead-letter companion of
        # every topic it consumes. This service produces to `festival-events` and consumes
        # `game-events` — a malformed/unhandled message on the latter is dead-lettered by
        # `Consumer._dead_letter` (app/platform/kafka.py) onto `game-events.dlq`, so that
        # topic has to exist too, or the dead-letter publish itself fails.
        return [
            self.topic_festival_events,
            f"{self.topic_festival_events}.dlq",
            f"{self.topic_game_events}.dlq",
        ]

    # --- read-through cache ------------------------------------------------
    # Empty disables it outright — public browsing still works with no Redis
    # running, just slower under repeated load.
    redis_url: str = ""
    cache_ttl_seconds: int = 30


@lru_cache
def get_config() -> Config:
    return Config()
