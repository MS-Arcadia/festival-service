from __future__ import annotations

from functools import lru_cache

from pydantic import Field

from app.platform.config import BaseConfig, CsvList


class Config(BaseConfig):
    service_name: str = "festival-service"
    http_port: int = 8091

    currency: str = "IRR"

    # --- kafka topics ---
    topic_game_events: str = "game-events"
    topic_festival_events: str = "festival-events"
    consumer_group: str = "festival-service"

    @property
    def owned_topics(self) -> list[str]:
        return [self.topic_festival_events]


    cors_origins: CsvList = Field(default_factory=lambda: ["http://localhost:3000"])


@lru_cache
def get_config() -> Config:
    return Config()  
