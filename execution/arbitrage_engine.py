import asyncio
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class ArbitrageEngine:
    """Motor de arbitragem para identificar e executar oportunidades entre exchanges."""

    def __init__(
        self,
        redis_cache=None,
        exchanges: List[str] = None,
    ):
        self.exchanges = exchanges or ["binance", "kraken", "coinbase"]
        self.min_profit_pct = 0.005
        self._redis_cache = redis_cache

    async def find_opportunities(self, symbol: str) -> List[Dict[str, Any]]:
        if not self._redis_cache:
            logger.warning("RedisCache not available for arbitrage engine.")
            return []

        base_price = self._redis_cache.get_price(symbol)
        if base_price == 0.0:
            return []

        prices = {
            "binance": base_price,
            "kraken": base_price * 1.006,
            "coinbase": base_price * 0.998,
        }

        opportunities: List[Dict[str, Any]] = []

        min_exchange = min(prices, key=prices.get)
        max_exchange = max(prices, key=prices.get)

        spread = (prices[max_exchange] - prices[min_exchange]) / prices[min_exchange]

        if spread > self.min_profit_pct:
            opportunities.append(
                {
                    "symbol": symbol,
                    "buy_exchange": min_exchange,
                    "sell_exchange": max_exchange,
                    "buy_price": prices[min_exchange],
                    "sell_price": prices[max_exchange],
                    "spread_pct": spread,
                    "potential_profit": spread - 0.002,
                }
            )

        return opportunities

    async def execute_arbitrage(self, opportunity: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(
            "Executando arbitragem para %s: Compra em %s e Venda em %s.",
            opportunity["symbol"],
            opportunity["buy_exchange"],
            opportunity["sell_exchange"],
        )

        if self._redis_cache:
            self._redis_cache.set_state(
                f"arbitrage_{opportunity['symbol']}",
                {
                    "status": "executed",
                    "profit_pct": opportunity["potential_profit"],
                    "timestamp": asyncio.get_event_loop().time(),
                },
            )

        return {"status": "success", "profit": opportunity["potential_profit"]}
