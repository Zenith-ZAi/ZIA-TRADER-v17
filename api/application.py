"""FastAPI application factory and process-scoped lifespan ownership."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from api.routers.auth import router as auth_router
from api.routers.engines import router as engines_router
from api.routers.health import router as health_router
from api.routers.market import router as market_router
from api.routers.operations import router as operations_router
from api.runtime_services import start_engine, stop_engine_tasks
from api.middleware import CorrelationIdMiddleware, RequestRateLimitMiddleware
from config.settings import Settings, settings as default_settings
from config.startup_validation import validate_startup_configuration

logger = logging.getLogger(__name__)
RuntimeBuilder = Callable[[Settings], Awaitable[Any]]


def create_app(
    app_settings: Settings | None = None,
    *,
    runtime_builder: RuntimeBuilder | None = None,
) -> FastAPI:
    """Create an isolated ASGI app; no DB, manager, or network IO occurs here.

    `runtime_builder` is injectable for tests and alternate process composition.
    Its default is imported lazily inside the lifespan to keep heavyweight trading
    and ML dependencies off API module-import paths.
    """
    config = app_settings or default_settings

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.runtime = None
        application.state.engine_tasks = {}
        application.state.engine_start_lock = None
        try:
            validate_startup_configuration(config)
            from monitoring.structured_logging import configure_json_logging
            from monitoring.telemetry.telemetry_setup import setup_telemetry

            configure_json_logging()
            setup_telemetry(application, app_settings=config)
            builder = runtime_builder
            if builder is None:
                from api.application_runtime import build_application_runtime

                builder = build_application_runtime
            runtime = await builder(config)
            application.state.runtime = runtime
            if config.AUTO_START_ENGINES:
                try:
                    from api.runtime_services import ensure_reconciliation_ok

                    await ensure_reconciliation_ok(application, "auto-start")
                except HTTPException as exc:
                    logger.error("Motores não iniciados após restart: %s", exc.detail)
                else:
                    await start_engine(
                        application,
                        "trading",
                        runtime.trading_manager.start_trading,
                        preflight=False,
                    )
                    if config.SNIPER_ENABLED:
                        await start_engine(
                            application,
                            "sniper",
                            runtime.trading_manager.start_sniper,
                            preflight=False,
                        )
                    else:
                        logger.info(
                            "SNIPER_ENABLED=false; somente o motor principal foi considerado no auto-start."
                        )
            else:
                logger.info("Motores não iniciados automaticamente; use os endpoints de controle.")
            yield
        finally:
            logger.info("Desligando motores e encerrando runtime ASGI...")
            await stop_engine_tasks(application)
            runtime = getattr(application.state, "runtime", None)
            application.state.runtime = None
            if runtime is not None:
                await runtime.close()
            logger.info("Runtime ASGI encerrado.")

    application = FastAPI(
        title=config.PROJECT_NAME,
        version=config.VERSION,
        lifespan=lifespan,
    )
    application.state.settings = config
    application.state.runtime = None
    application.state.engine_tasks = {}
    application.state.engine_start_lock = None

    application.include_router(health_router)
    application.include_router(auth_router)
    application.include_router(operations_router)
    application.include_router(market_router)
    application.include_router(engines_router)

    allowed_origins = [
        origin.strip()
        for origin in config.CORS_ALLOWED_ORIGINS.split(",")
        if origin.strip()
    ]
    application.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=config.CORS_ALLOW_CREDENTIALS,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    application.add_middleware(RequestRateLimitMiddleware, settings=config)
    application.add_middleware(CorrelationIdMiddleware)
    return application
