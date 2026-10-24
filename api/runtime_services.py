"""Application-scoped runtime status and engine lifecycle operations."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import HTTPException

logger = logging.getLogger(__name__)


def engine_tasks_for(application: Any) -> dict[str, asyncio.Task[Any]]:
    tasks = getattr(application.state, "engine_tasks", None)
    if tasks is None:
        tasks = {}
        application.state.engine_tasks = tasks
    return tasks


def engine_lifecycle_lock(application: Any) -> asyncio.Lock:
    lock = getattr(application.state, "engine_start_lock", None)
    if lock is None:
        lock = asyncio.Lock()
        application.state.engine_start_lock = lock
    return lock


def runtime_status_payload(application: Any) -> dict[str, Any]:
    runtime = get_runtime_from_application(application)
    manager = runtime.trading_manager
    tasks = engine_tasks_for(application)
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "engines": {
            name: bool(task and not task.done())
            for name, task in tasks.items()
        },
        "runtime": manager.runtime_status(),
        "exchange": {
            "connected": manager.exchange_connector.is_connected,
            "mode": application.state.settings.BINANCE_MODE,
        },
        "redis": manager.redis_cache.health(),
        "news_providers": manager.news_processor.health(),
    }


def get_runtime_from_application(application: Any) -> Any:
    runtime = getattr(application.state, "runtime", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail="application_runtime_not_started")
    return runtime


def health_payload(application: Any) -> dict[str, Any]:
    settings = application.state.settings
    runtime = get_runtime_from_application(application)
    db_manager = runtime.db_manager
    manager = runtime.trading_manager
    try:
        with db_manager.engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        database_persistent = not settings.DATABASE_URL.startswith("sqlite:")
        redis_health = manager.redis_cache.health()
        if settings.REQUIRE_PERSISTENT_DATABASE and not database_persistent:
            raise RuntimeError("PostgreSQL persistente obrigatório")
        if settings.REQUIRE_PERSISTENT_REDIS and not bool(redis_health.get("persistent")):
            raise RuntimeError("Redis persistente obrigatório")
        providers = manager.news_processor.health()
        latest = db_manager.get_ai_observations(limit=1)
        last_data_timestamp = (
            latest[0].observed_at.isoformat()
            if latest and latest[0].observed_at
            else None
        )
        provider_degraded = (
            any(not bool(value.get("ok", False)) for value in providers.values())
            if providers
            else False
        )
        return {
            "status": "degraded" if provider_degraded else "ok",
            "service": settings.PROJECT_NAME,
            "version": settings.VERSION,
            "exchange_connected": manager.exchange_connector.is_connected,
            "database": {"persistent": database_persistent, "reachable": True},
            "redis": redis_health,
            "news_providers": providers,
            "last_data_timestamp": last_data_timestamp,
            "engines": {
                name: bool(task and not task.done())
                for name, task in engine_tasks_for(application).items()
            },
            "live_trading_enabled": False,
            "live_mode": False,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Falha no healthcheck: %s", exc)
        raise HTTPException(status_code=503, detail="service_unhealthy") from exc


async def ensure_reconciliation_ok(application: Any, name: str) -> None:
    """Block engine start whenever order recovery is not explicitly healthy."""
    runtime = get_runtime_from_application(application)
    try:
        reconciliation = await runtime.trading_manager.reconcile()
    except Exception as exc:
        logger.exception("Reconciliação pré-start falhou; motor %s permanecerá parado.", name)
        raise HTTPException(
            status_code=503,
            detail="Reconciliação de ordens indisponível; início do motor bloqueado.",
        ) from exc
    if reconciliation.get("status") != "ok":
        logger.error("Reconciliação pré-start requer atenção; motor %s permanecerá parado.", name)
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Reconciliação de ordens requer intervenção; início do motor bloqueado.",
                "reconciliation": reconciliation,
            },
        )


async def start_engine(
    application: Any,
    name: str,
    factory: Callable[[], Any],
    *,
    preflight: bool = True,
) -> bool:
    """Start one engine per app after connection and fail-closed reconciliation."""
    settings = application.state.settings
    runtime = get_runtime_from_application(application)
    if name == "sniper" and not bool(getattr(settings, "SNIPER_ENABLED", False)):
        raise HTTPException(status_code=409, detail="sniper_disabled: SNIPER_ENABLED=false")
    async with engine_lifecycle_lock(application):
        tasks = engine_tasks_for(application)
        current_task = tasks.get(name)
        if current_task and not current_task.done():
            return False
        connector = runtime.trading_manager.exchange_connector
        if not connector.is_connected:
            await connector.connect()
        if preflight:
            await ensure_reconciliation_ok(application, name)
        task = asyncio.create_task(factory(), name=f"zia-{name}")
        tasks[name] = task
        return True


async def stop_engines(application: Any, manager: Any) -> None:
    """Linearize stop against in-flight starts, then cancel their tasks."""
    async with engine_lifecycle_lock(application):
        try:
            await manager.stop_engines()
        finally:
            await stop_engine_tasks(application)


async def stop_engine_tasks(application: Any) -> None:
    tasks_by_name = engine_tasks_for(application)
    tasks = [task for task in tasks_by_name.values() if not task.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    tasks_by_name.clear()
