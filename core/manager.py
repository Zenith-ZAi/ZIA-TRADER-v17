import asyncio
import logging
from typing import Dict, Any, List

from config.settings import Settings
from core.engine import RoboTraderUnified
from core.sniper_engine import SniperEngine
from core.backtest_engine import BacktestEngine

from data.news_processor import NewsProcessor
from execution.exchange_connector import ExchangeConnector
from execution.market_connector import MarketConnector
from execution.order_manager import OrderManager
from infra.redis_cache import RedisCache
from ai.whale_detector import WhaleDetector
from execution.execution_engine import ExecutionEngine
from core.runtime_registry import RuntimeConfigRegistry
from core.command_manager import CoreCommandManager
from core.daily_state_manager import DailyStateManager

logger = logging.getLogger(__name__)

class TradingManager:
    """Gerenciador principal que orquestra os diferentes motores de trading e backtesting."""

    def __init__(self, settings: Settings, db_manager):
        self.settings = settings
        self.runtime_registry = RuntimeConfigRegistry(db_manager)
        self.runtime_profile = self.runtime_registry.apply_to_settings(settings)
        self.daily_state = DailyStateManager(max_wins=5, max_losses=2)
        self.news_processor = NewsProcessor(settings, db_manager)
        base_exchange_connector = ExchangeConnector(settings)
        self.market_connector = MarketConnector(settings, base_exchange_connector)
        self.exchange_connector = self.market_connector
        
        self.redis_cache = RedisCache(settings.REDIS_URL)
        self.whale_detector = WhaleDetector(settings, db_manager)
        self.execution_engine = ExecutionEngine(
            settings,
            self.market_connector,
            self.redis_cache,
            db_manager=db_manager,
            account_id="default_account",
        )

        self.order_manager = OrderManager(settings, self.market_connector, self.execution_engine)
        self.reconciler = self.execution_engine.reconciler
        self.command_manager = CoreCommandManager(settings, db_manager, self.market_connector, self.news_processor)
        self.trading_engine = RoboTraderUnified(settings, self.news_processor, self.market_connector, db_manager)
        self.trading_engine.order_manager = self.order_manager
        self.sniper_engine = SniperEngine(
            settings,
            self.market_connector,
            self.execution_engine,
            self.whale_detector,
            self.redis_cache,
            db_manager,
            news_processor=self.news_processor,
        )
        self.sniper_engine.order_manager = self.order_manager
        self.backtest_engine = BacktestEngine(settings, db_manager)
        # self.arbitrage_engine = ArbitrageEngine(settings, self.exchange_connector) # Se houver um ArbitrageEngine real

    def reload_runtime_config(self) -> Dict[str, Any]:
        self.runtime_profile = self.runtime_registry.apply_to_settings(self.settings)
        self.order_manager.set_mode(self.settings.ORDER_MANAGER_MODE)
        self.trading_engine.refresh_runtime_config()
        self.sniper_engine.refresh_runtime_config()
        return self.runtime_profile

    def runtime_status(self) -> Dict[str, Any]:
        return {
            "profile": self.runtime_profile,
            "settings": {
                "symbols": list(self.settings.SYMBOLS),
                "timeframe": self.settings.TIMEFRAME,
                "analysis_timeframes": self.settings.ANALYSIS_TIMEFRAMES,
                "multi_timeframe_enabled": self.settings.MULTI_TIMEFRAME_ENABLED,
                "sniper_timeframe": self.settings.SNIPER_TIMEFRAME,
                "autonomous_trading_enabled": self.settings.AUTONOMOUS_TRADING_ENABLED,
                "shadow_mode_enabled": self.settings.SHADOW_MODE_ENABLED,
                "market_adapter": self.settings.MARKET_ADAPTER,
                "forex_mode": self.settings.FOREX_MODE,
                "binance_mode": self.settings.BINANCE_MODE,
                "order_manager_mode": self.order_manager.mode,
                "order_confirmation_required": self.order_manager.confirmation_required,
                "market_type": self.market_connector.market_type,
                "daily_state": self.daily_state.status(),
            },
        }

    async def trigger_kill_switch(self, reason: str = "manual", actor: str = "system") -> Dict[str, Any]:
        result = await self.exchange_connector.trigger_kill_switch(reason)
        if hasattr(self.settings, "LIVE_KILL_SWITCH"):
            self.settings.LIVE_KILL_SWITCH = True
        if hasattr(self, "reconciler") and self.reconciler is not None:
            self.db_manager.record_kill_switch(self.reconciler.account_id, True, reason, actor)
        return result

    async def reconcile(self) -> Dict[str, Any]:
        if self.reconciler is None:
            return {"status": "unsupported", "reason": "reconciler indisponível"}
        return await self.reconciler.reconcile()

    async def sync_positions(self) -> Dict[str, Any]:
        if self.reconciler is None:
            return {"status": "unsupported", "reason": "reconciler indisponível"}
        return await self.reconciler.sync_positions()

    async def start_trading(self):
        """Inicia o motor de trading principal (RoboTraderUnified)."""
        logger.info("Iniciando o motor de trading principal...")
        await self.trading_engine.start()

    async def start_sniper(self):
        """Inicia o motor Sniper."""
        logger.info("Iniciando o motor Sniper...")
        await self.sniper_engine.start()

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
