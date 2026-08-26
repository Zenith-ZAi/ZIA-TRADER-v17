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
    if settings.REQUIRE_PERSISTENT_DATABASE and settings.DATABASE_URL.startswith("sqlite:"):
        raise RuntimeError("PostgreSQL persistente obrigatório no ambiente do worker")
    db_manager.create_tables()
    manager = TradingManager(settings, db_manager)
    if settings.REQUIRE_PERSISTENT_REDIS and not manager.redis_cache.is_persistent:
        raise RuntimeError("Redis persistente obrigatório no ambiente do worker")
    await manager.exchange_connector.connect()
    reconciliation = await manager.reconcile()
    logger.info("Reconciliação inicial concluída: %s", reconciliation.get("status"))
    if reconciliation.get("status") == "error" and settings.AUTONOMOUS_TRADING_ENABLED:
        raise RuntimeError("reconciliação inicial falhou; autonomia permanece bloqueada")
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
