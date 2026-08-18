"""Processo separado para executar os motores em ambiente persistente."""

from __future__ import annotations

import asyncio
import logging

from config.settings import settings
from core.manager import TradingManager
from database_manager import DatabaseManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run_worker() -> None:
    db_manager = DatabaseManager(settings.DATABASE_URL)
    db_manager.create_tables()
    manager = TradingManager(settings, db_manager)
    await manager.exchange_connector.connect()
    tasks = [asyncio.create_task(manager.start_trading(), name="zia-worker-trading")]
    if settings.SNIPER_ENABLED:
        tasks.append(asyncio.create_task(manager.start_sniper(), name="zia-worker-sniper"))
    else:
        logger.info("Sniper desativado por configuração; apenas o motor principal foi iniciado.")
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        logger.info("Cancelamento recebido pelo worker.")
        raise
    finally:
        await manager.stop_all()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        logger.info("Worker encerrado pelo operador.")
