import asyncio
import ccxt.async_support as ccxt
from typing import Dict, Any, Optional
from config.settings import settings
from infra.redis_cache import redis_cache

class ExecutionEngine:
    """Motor de execução de ordens para interagir com exchanges."""
    def __init__(self, exchange_id: str = "binance"):
        self.exchange_id = exchange_id
        self.exchange = self._init_exchange()
        self.is_connected = False

    def _init_exchange(self):
        """Inicializa a instância da exchange usando CCXT."""
        params = {
            'apiKey': settings.BINANCE_API_KEY,
            'secret': settings.BINANCE_SECRET_KEY,
            'enableRateLimit': True,
            'options': {'defaultType': 'future'}
        }
        return getattr(ccxt, self.exchange_id)(params)

    async def connect(self):
        """Estabelece conexão com a exchange."""
        try:
            # Em produção, faríamos uma chamada de teste (ex: fetch_balance)
            # await self.exchange.fetch_balance()
            self.is_connected = True
            print(f"Conectado à exchange {self.exchange_id}.")
        except Exception as e:
            print(f"Erro ao conectar à exchange: {e}")
            self.is_connected = False

    async def execute_order(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Executa uma ordem de mercado ou limite na exchange."""
        if not self.is_connected:
            await self.connect()
            
        symbol = order_data.get("symbol")
        action = order_data.get("action")
        quantity = order_data.get("quantity", 0.0)
        
        if not symbol or not action or quantity <= 0:
            return {"status": "error", "reason": "Dados de ordem inválidos."}
            
        try:
            # Simulação de execução de ordem (em produção, usaríamos self.exchange.create_order)
            # order = await self.exchange.create_market_order(symbol, action, quantity)
            order_id = f"sim_{asyncio.get_event_loop().time()}"
            
            # Atualiza o estado da posição no cache Redis
            redis_cache.set_state(f"position_{symbol}", {
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
                "quantity": quantity
            }
        except Exception as e:
            print(f"Erro ao executar ordem para {symbol}: {e}")
            return {"status": "error", "reason": str(e)}

    async def close_connection(self):
        """Fecha a conexão com a exchange."""
        await self.exchange.close()

execution_engine = ExecutionEngine()
