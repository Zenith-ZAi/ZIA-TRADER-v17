from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pandas as pd

from config.settings import Settings

logger = logging.getLogger(__name__)


class SimulatedExchangeAdapter:
    """Adapter local determinístico o suficiente para testes sem rede."""

    def __init__(self) -> None:
        self.is_connected = False

    async def connect(self) -> None:
        await asyncio.sleep(0.01)
        self.is_connected = True
        logger.info("Conectado à exchange simulada.")

    async def close(self) -> None:
        await asyncio.sleep(0.01)
        self.is_connected = False

    async def get_historical_data(self, symbol: str, timeframe: str, limit: int = 100) -> pd.DataFrame:
        now = datetime.now(timezone.utc)
        data = {
            "timestamp": [now - pd.Timedelta(minutes=i) for i in range(limit)],
            "open": [random.uniform(1000, 50000) for _ in range(limit)],
            "high": [random.uniform(1000, 50000) for _ in range(limit)],
            "low": [random.uniform(1000, 50000) for _ in range(limit)],
            "close": [random.uniform(1000, 50000) for _ in range(limit)],
            "volume": [random.uniform(100, 10000) for _ in range(limit)],
        }
        return pd.DataFrame(data).set_index("timestamp").sort_index()

    async def get_market_data(self, symbol: str) -> Dict[str, Any]:
        price = random.uniform(1000, 50000)
        return {
            "symbol": symbol,
            "last": price,
            "bid": price * 0.999,
            "ask": price * 1.001,
            "volume": random.uniform(1000, 100000),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def place_order(self, symbol: str, action: str, order_type: str, quantity: float, price: Optional[float] = None) -> Dict[str, Any]:
        await asyncio.sleep(0.01)
        order_id = f"sim_{datetime.now(timezone.utc).timestamp()}_{random.randint(0, 9999)}"
        filled_price = price if price else random.uniform(1000, 50000)
        return {
            "status": "success",
            "order_id": order_id,
            "symbol": symbol,
            "action": action,
            "order_type": order_type,
            "filled_price": filled_price,
            "filled_quantity": quantity,
            "commission": quantity * filled_price * 0.001,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        return {"status": "success", "order_id": order_id, "message": "Simulated order cancelled"}

    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        return {"status": "FILLED", "order_id": order_id}

    async def get_account_balance(self) -> Dict[str, float]:
        return {"USDT": 10000.0, "BTC": 0.5}


class ExchangeConnector:
    """Fachada compatível com o sistema, com seleção segura de adapter."""

    def __init__(self, settings: Settings):
        self.settings = settings
        mode = settings.BINANCE_MODE.lower()
        if mode in {"testnet", "demo"}:
            from execution.binance_adapter import BinanceSpotAdapter

            self._adapter = BinanceSpotAdapter(settings)
            logger.info("ExchangeConnector inicializado em modo Binance %s.", mode)
        elif mode in {"simulated", "simulation", "mock"}:
            self._adapter = SimulatedExchangeAdapter()
            logger.info("ExchangeConnector inicializado em modo de simulação.")
        else:
            raise ValueError("BINANCE_MODE deve ser simulated, testnet ou demo.")

    @property
    def is_connected(self) -> bool:
        return bool(self._adapter.is_connected)

    async def connect(self) -> None:
        await self._adapter.connect()

    async def close(self) -> None:
        await self._adapter.close()

    async def get_historical_data(self, symbol: str, timeframe: str, limit: int = 100) -> pd.DataFrame:
        return await self._adapter.get_historical_data(symbol, timeframe, limit)

    async def get_market_data(self, symbol: str) -> Dict[str, Any]:
        return await self._adapter.get_market_data(symbol)

    async def place_order(self, symbol: str, action: str, order_type: str, quantity: float, price: Optional[float] = None) -> Dict[str, Any]:
        return await self._adapter.place_order(symbol, action, order_type, quantity, price)

    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        return await self._adapter.cancel_order(order_id)

    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        return await self._adapter.get_order_status(order_id)

    async def get_account_balance(self) -> Dict[str, float]:
        return await self._adapter.get_account_balance()
