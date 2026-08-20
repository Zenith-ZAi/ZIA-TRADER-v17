"""Adapters Forex seguros: paper local e contrato live fail-closed.

Nenhuma chamada externa é inventada. Um broker Forex real precisa de um
adapter específico validado para sua API, autenticação, rollover e regras de
lote; até lá, o modo paper é o único caminho permitido.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

import numpy as np
import pandas as pd


class ForexAdapterError(RuntimeError):
    pass


class ForexLiveAdapter:
    """Contrato explícito que não envia ordens sem implementação de broker."""

    def __init__(self, settings: Any):
        self.settings = settings
        self.is_connected = False

    async def connect(self) -> None:
        raise ForexAdapterError("Adapter Forex live não configurado; selecione um broker suportado e validado.")

    async def close(self) -> None:
        self.is_connected = False

    async def place_order(self, *args, **kwargs) -> Dict[str, Any]:
        raise ForexAdapterError("Ordens Forex live estão bloqueadas até configurar um adapter de broker.")


class ForexPaperAdapter:
    """Adapter paper determinístico para validar o core sem capital ou rede."""

    def __init__(self, settings: Any):
        self.settings = settings
        self.is_connected = False
        self._orders: Dict[str, Dict[str, Any]] = {}
        self._counter = 0
        self.spread = float(getattr(settings, "FOREX_PAPER_SPREAD", 0.0001))

    async def connect(self) -> None:
        self.is_connected = True

    async def close(self) -> None:
        self.is_connected = False

    @staticmethod
    def _base_price(symbol: str) -> float:
        return {"EUR/USD": 1.08, "GBP/USD": 1.27, "USD/JPY": 150.0}.get(symbol.upper(), 1.0)

    async def get_historical_data(self, symbol: str, timeframe: str, limit: int = 100) -> pd.DataFrame:
        if not self.is_connected:
            raise ForexAdapterError("Forex paper não está conectado")
        count = max(40, min(int(limit), 1000))
        end = pd.Timestamp.now(tz="UTC").floor("min")
        index = pd.date_range(end=end, periods=count, freq="min", tz="UTC")
        base = self._base_price(symbol)
        trend = np.linspace(0.0, base * 0.001, count)
        close = base + trend
        frame = pd.DataFrame(index=index)
        frame["open"] = close - base * 0.0001
        frame["high"] = close + base * 0.0002
        frame["low"] = close - base * 0.0002
        frame["close"] = close
        frame["volume"] = 1.0
        return frame

    async def get_market_data(self, symbol: str) -> Dict[str, Any]:
        price = self._base_price(symbol)
        return {
            "symbol": symbol,
            "last": price,
            "bid": price - self.spread / 2.0,
            "ask": price + self.spread / 2.0,
            "volume": 1.0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def get_order_book(self, symbol: str, limit: int = 20) -> Dict[str, Any]:
        market = await self.get_market_data(symbol)
        return {
            "symbol": symbol,
            "bids": [[market["bid"], 100000.0]],
            "asks": [[market["ask"], 100000.0]],
            "limit": limit,
        }

    async def place_order(self, symbol: str, action: str, order_type: str, quantity: float, price: float | None = None) -> Dict[str, Any]:
        if not self.is_connected:
            return {"status": "error", "reason": "Forex paper não está conectado"}
        if action not in {"buy", "sell"} or quantity <= 0:
            return {"status": "error", "reason": "ordem Forex paper inválida"}
        self._counter += 1
        market = await self.get_market_data(symbol)
        filled_price = float(price or market["ask"] if action == "buy" else price or market["bid"])
        order_id = f"forex_paper_{self._counter}"
        result = {
            "status": "success",
            "order_id": order_id,
            "symbol": symbol,
            "action": action,
            "order_type": order_type,
            "filled_price": filled_price,
            "filled_quantity": float(quantity),
            "commission": 0.0,
        }
        self._orders[order_id] = result
        return result

    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        return {"status": "success", "order_id": order_id}

    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        return {"status": "FILLED" if order_id in self._orders else "UNKNOWN", "order_id": order_id}

    async def get_account_balance(self) -> Dict[str, float]:
        return {"USD": 10000.0}

    async def normalize_order_values(self, symbol: str, quantity: float, price: float | None = None) -> Dict[str, float]:
        result = {"quantity": float(quantity)}
        if price is not None:
            result["price"] = float(price)
        return result
