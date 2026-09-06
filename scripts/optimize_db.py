"""Otimização de Banco de Dados: Preparação para Particionamento.
Garante que DecisionSnapshots e MarketData suportem o volume de 5 anos.
"""

from __future__ import annotations

import logging
from sqlalchemy import create_async_engine, text
from config.settings import Settings

logger = logging.getLogger(__name__)

async def prepare_partitioning():
    settings = Settings()
    if "postgresql" not in settings.DATABASE_URL:
        logger.info("Particionamento nativo ignorado para SQLite. Recomendado migrar para PostgreSQL no VPS.")
        return

    engine = create_async_engine(settings.DATABASE_URL)
    async with engine.begin() as conn:
        # Exemplo de criação de tabela particionada por mês para Snapshots
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS decision_snapshots_partitioned (
                id SERIAL,
                timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
                symbol TEXT NOT NULL,
                data JSONB,
                PRIMARY KEY (id, timestamp)
            ) PARTITION BY RANGE (timestamp);
        """))
        logger.info("Tabela particionada preparada no PostgreSQL.")

if __name__ == "__main__":
    import asyncio
    asyncio.run(prepare_partitioning())
