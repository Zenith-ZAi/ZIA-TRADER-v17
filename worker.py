"""Processo separado para executar os motores em ambiente persistente."""

from __future__ import annotations

import asyncio
import logging

from config.settings import settings
from core.manager import TradingManager
from database_manager import DatabaseManager
from monitoring.structured_logging import configure_json_logging

configure_json_logging()
logger = logging.getLogger(__name__)


async def run_worker() -> None:
    db_manager = DatabaseManager(settings.DATABASE_URL)
    manager = None
    tasks: list[asyncio.Task] = []
    try:
        if settings.REQUIRE_PERSISTENT_DATABASE and settings.DATABASE_URL.startswith("sqlite:"):
            raise RuntimeError("PostgreSQL persistente obrigatório no ambiente do worker")
        db_manager.create_tables()
        manager = TradingManager(settings, db_manager)
        if settings.REQUIRE_PERSISTENT_REDIS and not manager.redis_cache.is_persistent:
            raise RuntimeError("Redis persistente obrigatório no ambiente do worker")
        await manager.exchange_connector.connect()
        reconciliation = await manager.reconcile()
        reconciliation_status = reconciliation.get("status") if isinstance(reconciliation, dict) else None
        logger.info("Reconciliação inicial concluída: %s", reconciliation_status or "unknown")

        if not settings.AUTO_START_ENGINES:
            logger.info("AUTO_START_ENGINES=false; serviços de infraestrutura verificados, nenhum motor de negociação será iniciado.")
            if reconciliation_status != "ok":
                logger.warning("Reconciliação exige intervenção; engines permanecem bloqueadas: %s", reconciliation)
            return

        if reconciliation_status != "ok":
            logger.error("Reconciliação não saudável/completa; motores permanecem bloqueados: %s", reconciliation)
            raise RuntimeError("reconciliação inicial não está explicitamente saudável; engines não iniciadas")

        tasks.append(asyncio.create_task(manager.start_trading(), name="zia-worker-trading"))
        if settings.SNIPER_ENABLED:
            tasks.append(asyncio.create_task(manager.start_sniper(), name="zia-worker-sniper"))
        else:
            logger.info("SNIPER_ENABLED=false; somente o motor principal foi habilitado pelo auto-start.")

        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        logger.info("Cancelamento recebido pelo worker.")
        raise
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if manager is not None:
            await manager.stop_all()
        db_manager.engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        logger.info("Worker encerrado pelo operador.")
