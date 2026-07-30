from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.adapters.inbound.consumer import Handlers
from app.adapters.inbound.rest import festivals
from app.adapters.outbound.auth_profile import HttpAuthProfileDirectory
from app.adapters.outbound.publisher import OutboxEventPublisher
from app.adapters.outbound.repositories import (
    PostgresCatalogGameRepository,
    PostgresFestivalRepository,
    PostgresPromotionRepository,
)
from app.application.catalog_sync_service import CatalogSyncService
from app.application.festival_service import FestivalService
from app.config import Config, get_config
from app.platform import health, kafka, migrate
from app.platform import logging as logx
from app.platform.auth import Verifier
from app.platform.db import UnitOfWork, create_engine, create_session_factory, strip_asyncpg_dsn
from app.platform.events import new_id
from app.platform.http import (
    install_error_handlers,
    install_middleware,
    install_operational_routes,
)
from app.platform.outbox import Dispatcher

logger = logging.getLogger(__name__)

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


def build(config: Config | None = None) -> FastAPI:
    cfg = config or get_config()

    logx.configure(
        service=cfg.service_name,
        version=cfg.service_version,
        level=cfg.log_level,
        json_format=cfg.log_json,
    )

    engine = create_engine(
        cfg.database_url,
        pool_size=cfg.db_pool_size,
        max_overflow=cfg.db_max_overflow,
        echo=cfg.db_echo,
    )
    sessions = create_session_factory(engine)
    uow = UnitOfWork(sessions)

    festival_repo = PostgresFestivalRepository()
    catalog_game_repo = PostgresCatalogGameRepository()
    promotion_repo = PostgresPromotionRepository()
    publisher = OutboxEventPublisher(cfg)
    clock = SystemClock()

    users = HttpAuthProfileDirectory(
        base_url=cfg.auth_profile_base_url,
        jwt_secret=cfg.jwt_secret,
        jwt_algorithm=cfg.jwt_algorithm,
        jwt_issuer=cfg.jwt_issuer,
        jwt_audience=cfg.jwt_audience,
        service_name=cfg.service_name,
        timeout=cfg.auth_profile_timeout_seconds,
    )

    festival_service = FestivalService(
        uow=uow,
        festivals=festival_repo,
        catalog_games=catalog_game_repo,
        promotions=promotion_repo,
        publisher=publisher,
        clock=clock,
        new_id=new_id,
        users=users,
    )
    catalog_sync_service = CatalogSyncService(
        uow=uow,
        festivals=festival_repo,
        catalog_games=catalog_game_repo,
        promotions=promotion_repo,
        publisher=publisher,
        clock=clock,
    )

    producer = kafka.Producer(cfg.kafka_brokers, cfg.service_name) if cfg.kafka_enabled else None
    dispatcher = (
        Dispatcher(
            sessions,
            producer,
            interval=cfg.outbox_interval_seconds,
            batch_size=cfg.outbox_batch_size,
        )
        if producer is not None
        else None
    )
    consumer: kafka.Consumer | None = None

    probes = health.Registry(service=cfg.service_name, version=cfg.service_version)

    async def check_database() -> None:
        async with sessions() as session:
            await session.execute(text("SELECT 1"))

    probes.add("postgres", check_database, critical=True)

    if producer is not None:

        async def check_outbox() -> None:
            backlog = await dispatcher.backlog()
            if backlog > 5_000:
                raise RuntimeError(f"outbox backlog is {backlog}")

        probes.add("outbox", check_outbox, critical=False)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if cfg.run_migrations:
            applied = await migrate.run(strip_asyncpg_dsn(cfg.database_url), MIGRATIONS)
            logger.info("migrations up to date", extra={"applied": applied})

        if producer is not None:
            await producer.start()
            if cfg.kafka_ensure_topics:
                await kafka.ensure_topics(
                    cfg.kafka_brokers,
                    cfg.owned_topics,
                    partitions=cfg.kafka_topic_partitions,
                    replication=cfg.kafka_topic_replication,
                )
            await dispatcher.start()

            nonlocal consumer
            consumer = kafka.Consumer(
                cfg.kafka_brokers,
                topic=cfg.topic_game_events,
                group_id=cfg.consumer_group,
                router=Handlers(catalog_sync_service).game_events_router(),
                producer=producer,
            )
            await consumer.start()

        logger.info(
            "festival-service started",
            extra={
                "environment": cfg.environment,
                "kafka": cfg.kafka_enabled,
                "port": cfg.http_port,
            },
        )
        try:
            yield
        finally:
            if consumer is not None:
                await consumer.stop()
            if dispatcher is not None:
                await dispatcher.stop()
            if producer is not None:
                await producer.stop()
            await users.aclose()
            await engine.dispose()
            logger.info("festival-service stopped")

    app = FastAPI(
        title="Arcadia Festival Service",
        version=cfg.service_version,
        description=(
            "Platform-run sales. Admin creates a festival and selects the games in "
            "it; the discount on any one of those games is decided in the catalog "
            "service, by Support and the developer, and reported back here."
        ),
        lifespan=lifespan,
        docs_url="/docs" if not cfg.is_production else None,
        redoc_url=None,
    )

    app.state.config = cfg
    app.state.verifier = Verifier(
        secret=cfg.jwt_secret,
        public_key=cfg.jwt_public_key,
        algorithm=cfg.jwt_algorithm,
        issuer=cfg.jwt_issuer,
        audience=cfg.jwt_audience,
    )
    app.state.festival_service = festival_service
    app.state.catalog_sync_service = catalog_sync_service
    app.state.uow = uow
    app.state.sessions = sessions

    if cfg.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cfg.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-Correlation-ID"],
        )

    install_middleware(app, service=cfg.service_name)
    install_error_handlers(app)
    install_operational_routes(app, readiness=probes.report)

    app.include_router(festivals.router)

    return app
