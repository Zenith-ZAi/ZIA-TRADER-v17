import asyncio
import logging
from typing import Dict, Any, List

from config.settings import Settings
from core.engine import RoboTraderUnified
from core.sniper_engine import SniperEngine
from core.backtest_engine import BacktestEngine

from data.news_processor import NewsProcessor
from execution.exchange_connector import ExchangeConnector
from infra.redis_cache import RedisCache
from ai.whale_detector import WhaleDetector
from execution.execution_engine import ExecutionEngine

logger = logging.getLogger(__name__)

class TradingManager:
    """Gerenciador principal que orquestra os diferentes motores de trading e backtesting."""

    def __init__(self, settings: Settings, db_manager):
        self.settings = settings
        self.news_processor = NewsProcessor(settings)
        self.exchange_connector = ExchangeConnector(settings)
        
        self.redis_cache = RedisCache(settings.REDIS_URL)
        self.whale_detector = WhaleDetector(settings, db_manager)
        self.execution_engine = ExecutionEngine(settings, self.exchange_connector, self.redis_cache)

        self.trading_engine = RoboTraderUnified(settings, self.news_processor, self.exchange_connector, db_manager)
        self.sniper_engine = SniperEngine(settings, self.exchange_connector, self.execution_engine, self.whale_detector, self.redis_cache, db_manager)
        self.backtest_engine = BacktestEngine(settings, db_manager)
        self._trading_task = None
        self._sniper_task = None
        # self.arbitrage_engine = ArbitrageEngine(settings, self.exchange_connector) # Se houver um ArbitrageEngine real

    async def start_trading(self):
        """Inicia o motor de trading principal (RoboTraderUnified)."""
        if self.trading_engine.is_running:
            logger.warning("Motor de trading já está em execução; segunda instância ignorada.")
            return
        logger.info("Iniciando o motor de trading principal...")
        self._trading_task = asyncio.current_task()
        try:
            await self.trading_engine.start()
        finally:
            self._trading_task = None

    async def start_sniper(self):
        """Inicia o motor Sniper."""
        if self.sniper_engine.is_running:
            logger.warning("Motor Sniper já está em execução; segunda instância ignorada.")
            return
        logger.info("Iniciando o motor Sniper...")
        self._sniper_task = asyncio.current_task()
        try:
            await self.sniper_engine.start()
        finally:
            self._sniper_task = None

    async def run_backtest(self, symbol: str, historical_data: Any, strategy_name: str) -> Dict[str, Any]:
        """Executa um backtest para uma estratégia específica."""
        logger.info(f"Executando backtest para {symbol} com estratégia {strategy_name}...")
        return await self.backtest_engine.run(symbol, historical_data, strategy_name)

    async def stop_all(self):
        """Para todos os motores de trading ativos."""
        logger.info("Parando todos os motores de trading...")
        await self.trading_engine.stop()
        await self.sniper_engine.stop() # Se o sniper_engine tiver um método stop
        await self.news_processor.close()
        await self.exchange_connector.close()
        logger.info("Todos os motores parados.")
