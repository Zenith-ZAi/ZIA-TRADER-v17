"""Ownership of database and trading resources for the FastAPI application."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Callable

from config.settings import Settings
from core.manager import TradingManager
from database_manager import DatabaseManager

logger = logging.getLogger(__name__)


@dataclass
class ApplicationRuntime:
    """Resources whose lifetime is bounded by one ASGI application lifespan."""

    db_manager: DatabaseManager
    trading_manager: TradingManager
    _closed: bool = False

    async def close(self) -> None:
        """Close engines/providers before releasing the database connection pool."""
        if self._closed:
            return
        self._closed = True
        try:
            await self.trading_manager.stop_all()
        finally:
            self.db_manager.engine.dispose()


async def build_application_runtime(
    settings: Settings,
    *,
    database_factory: Callable[[str], DatabaseManager] | None = None,
    manager_factory: Callable[[Settings, DatabaseManager], TradingManager] | None = None,
) -> ApplicationRuntime:
    """Build and connect runtime resources only after ASGI startup begins.

    Alembic/SQLAlchemy schema setup is synchronous and can block on PostgreSQL,
    so it is isolated from the ASGI event loop. TradingManager construction is
    kept after migration because its repositories expect a ready schema.
    """
    db_factory = database_factory or DatabaseManager
    trading_factory = manager_factory or TradingManager
    db_manager = db_factory(settings.DATABASE_URL)
    trading_manager = None
    try:
        await asyncio.to_thread(db_manager.create_tables)
        trading_manager = trading_factory(settings, db_manager)
        await trading_manager.exchange_connector.connect()
        return ApplicationRuntime(db_manager, trading_manager)
    except BaseException:
        try:
            if trading_manager is not None:
                await trading_manager.stop_all()
        except Exception:
            logger.exception("Falha ao limpar TradingManager após startup incompleto.")
        finally:
            db_manager.engine.dispose()
        raise
