import asyncio
import logging
from typing import Dict, Any, Optional
from config.settings import Settings
from infra.redis_cache import RedisCache
from execution.exchange_connector import ExchangeConnector

logger = logging.getLogger(__name__)

class ExecutionEngine:
    """Motor de execução de ordens para interagir com exchanges."""
    def __init__(self, settings: Settings, exchange_connector: ExchangeConnector, redis_cache: RedisCache):
        self.settings = settings
        self.exchange_connector = exchange_connector
        self.redis_cache = redis_cache
        self.is_connected = True # Assume connected via ExchangeConnector

    async def execute_order(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Executa uma ordem de mercado ou limite na exchange."""
        symbol = order_data.get("symbol")
        action = order_data.get("action")
        quantity = order_data.get("quantity", 0.0)
        
        if not symbol or not action or quantity <= 0:
            return {"status": "error", "reason": "Dados de ordem inválidos."}
            
        try:
            order_result = await self.exchange_connector.place_order(symbol, action, "market", quantity, order_data.get("price"))
            if order_result["status"] == "failed":
                raise Exception(order_result["error"])
            order_id = order_result["order_id"]
            
            # Atualiza o estado da posição no cache Redis
            self.redis_cache.set_state(f"position_{symbol}", {
                "symbol": symbol,
                "action": action,
                "quantity": quantity,
                "entry_price": order_data.get("price"),
                "status": "open",
                "order_id": order_id
            })
            
            return {
                "status": "success",
                "order_id": order_id,
                "symbol": symbol,
                "action": action,
                "quantity": quantity,
                "filled_price": order_result.get("filled_price", 0.0),
                "filled_quantity": order_result.get("filled_quantity", 0.0),
                "commission": order_result.get("commission", 0.0)
            }
        except Exception as e:
            logger.error(f"Erro ao executar ordem para {symbol}: {e}")
            return {"status": "error", "reason": str(e)}
