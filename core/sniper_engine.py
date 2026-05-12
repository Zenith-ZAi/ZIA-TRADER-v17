import asyncio
import logging
from typing import Dict, Any

from config.settings import Settings
from infra.redis_cache import RedisCache
from execution.execution_engine import ExecutionEngine
from ai.whale_detector import WhaleDetector
from execution.exchange_connector import ExchangeConnector
from database import save_trade

logger = logging.getLogger(__name__)


class SniperEngine:
    """Motor Sniper para execução rápida em eventos de alta volatilidade."""

    def __init__(
        self,
        settings: Settings,
        exchange_connector: ExchangeConnector,
        execution_engine: ExecutionEngine,
        whale_detector: WhaleDetector,
        redis_cache: RedisCache,
    ):
        self.settings = settings
        self.exchange_connector = exchange_connector
        self.execution_engine = execution_engine
        self.whale_detector = whale_detector
        self.redis_cache = redis_cache
        self.is_running = False
        self.symbols = self.settings.SYMBOLS
        self.volatility_threshold = self.settings.SNIPER_VOLATILITY_THRESHOLD

    async def start(self):
        """Inicia o motor Sniper."""
        self.is_running = True
        logger.info("Motor Sniper ZIA iniciado.")

        while self.is_running:
            try:
                for symbol in self.symbols:
                    current_market_data = (
                        await self.exchange_connector.get_market_data(symbol)
                    )
                    historical_data = (
                        await self.exchange_connector.get_historical_data(
                            symbol, self.settings.SNIPER_TIMEFRAME
                        )
                    )
                    current_price = (
                        current_market_data.get("last")
                        if current_market_data
                        else None
                    )

                    if current_price is None:
                        logger.warning(
                            "[%s] Sniper: preço indisponível. Pulando.", symbol
                        )
                        continue

                    previous_price_key = f"prev_price_sniper_{symbol}"
                    previous_price = self.redis_cache.get_state(previous_price_key)

                    if previous_price:
                        price_change = (
                            abs(current_price - float(previous_price))
                            / float(previous_price)
                        )

                        current_order_flow = {
                            "symbol": symbol,
                            "total_volume": current_market_data.get("volume", 0),
                            "buys": [],
                            "sells": [],
                        }
                        whale_activity = self.whale_detector.detect_whale_activity(
                            historical_data, current_order_flow
                        )
                        if (
                            whale_activity["detected"]
                            and whale_activity["magnitude"]
                            > self.settings.WHALE_ACTIVITY_SNIPER_THRESHOLD
                        ):
                            logger.info(
                                "Sniper: Baleia detectada para %s (mag %.2f)",
                                symbol,
                                whale_activity["magnitude"],
                            )

                        if price_change > self.volatility_threshold:
                            logger.info(
                                "Sniper: Alta volatilidade em %s: %.2f%%",
                                symbol,
                                price_change * 100,
                            )

                            action = (
                                "buy"
                                if current_price > float(previous_price)
                                else "sell"
                            )
                            order_data: Dict[str, Any] = {
                                "symbol": symbol,
                                "action": action,
                                "quantity": self.settings.SNIPER_TRADE_QUANTITY,
                                "price": current_price,
                                "confidence": 0.95,
                            }

                            execution_result = (
                                await self.execution_engine.execute_order(order_data)
                            )

                            if execution_result["status"] == "success":
                                logger.info(
                                    "Sniper: Ordem executada: %s",
                                    execution_result["order_id"],
                                )
                                await save_trade(
                                    {
                                        "symbol": symbol,
                                        "action": action,
                                        "quantity": self.settings.SNIPER_TRADE_QUANTITY,
                                        "price": current_price,
                                        "status": "open",
                                        "order_id": execution_result["order_id"],
                                    }
                                )

                    self.redis_cache.set_state(
                        previous_price_key,
                        str(current_price),
                        expire=self.settings.SNIPER_PRICE_CACHE_EXPIRE,
                    )

                await asyncio.sleep(self.settings.SNIPER_CYCLE_INTERVAL_SECONDS)
            except Exception as e:
                logger.error("Erro no loop do motor Sniper: %s", e)
                await asyncio.sleep(self.settings.ERROR_RETRY_INTERVAL)

    async def stop(self):
        """Para o motor Sniper."""
        self.is_running = False
        logger.info("Motor Sniper ZIA parado.")
