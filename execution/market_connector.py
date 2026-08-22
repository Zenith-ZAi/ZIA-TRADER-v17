"""Fachada unificada para cripto, Forex e dados B3.

O caminho padrão continua sendo o ExchangeConnector existente. CCXT e Yahoo
são opcionais e nunca habilitam ordens live por si só. B3 é somente leitura até
que exista uma corretora brasileira explicitamente implementada e homologada.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pandas as pd
import requests

from config.settings import Settings
from execution.exchange_connector import ExchangeConnector

logger = logging.getLogger(__name__)


class MarketConnectorError(RuntimeError):
    pass


def normalize_symbol(symbol: str, market: str = "crypto") -> str:
    value = str(symbol or "").strip().upper()
    if not value:
        raise ValueError("símbolo vazio")
    market = market.lower()
    if market in {"crypto", "binance", "ccxt", "spot", "futures"}:
        return value.replace("/", "").replace("-", "").replace("_", "")
    if market in {"forex", "fx"}:
        compact = value.replace("/", "").replace("-", "").replace("_", "")
        if len(compact) == 6:
            return f"{compact[:3]}/{compact[3:]}"
        return value if "/" in value else value
    if market in {"b3", "stocks", "stock"}:
        return value if value.endswith(".SA") else f"{value}.SA"
    return value


class YahooB3Adapter:
    """Dados públicos Yahoo para B3, sem caminho de escrita."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.is_connected = False
        self.base_url = str(getattr(settings, "YAHOO_FINANCE_BASE_URL", "https://query1.finance.yahoo.com/v8/finance/chart"))
        self.timeout = float(getattr(settings, "NEWS_HTTP_TIMEOUT_SECONDS", 8.0))

    async def connect(self) -> None:
        self.is_connected = True

    async def close(self) -> None:
        self.is_connected = False

    def _chart(self, symbol: str, interval: str = "1h", limit: int = 100) -> pd.DataFrame:
        normalized = normalize_symbol(symbol, "b3")
        period = max(2, int(limit))
        response = requests.get(
            f"{self.base_url}/{normalized}",
            params={"range": "1y", "interval": interval, "events": "history"},
            headers={"User-Agent": "ZIA-Trader-readonly/1.0"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json().get("chart", {}).get("result", [])
        if not payload:
            raise MarketConnectorError(f"Yahoo não retornou dados para {normalized}")
        result = payload[0]
        timestamps = result.get("timestamp", [])
        quote = (result.get("indicators", {}).get("quote", [{}]) or [{}])[0]
        frame = pd.DataFrame({
            "timestamp": pd.to_datetime(timestamps, unit="s", utc=True),
            "open": quote.get("open", []),
            "high": quote.get("high", []),
            "low": quote.get("low", []),
            "close": quote.get("close", []),
            "volume": quote.get("volume", []),
        }).dropna(subset=["close"]).tail(period).set_index("timestamp")
        if frame.empty:
            raise MarketConnectorError(f"Yahoo retornou série vazia para {normalized}")
        return frame

    async def get_historical_data(self, symbol: str, timeframe: str, limit: int = 100) -> pd.DataFrame:
        if not self.is_connected:
            raise MarketConnectorError("Yahoo B3 não está conectado")
        interval = timeframe if timeframe in {"1m", "5m", "15m", "30m", "1h", "1d", "1wk"} else "1h"
        return self._chart(symbol, interval=interval, limit=limit)

    async def get_market_data(self, symbol: str) -> Dict[str, Any]:
        frame = await self.get_historical_data(symbol, "1h", 2)
        price = float(frame["close"].iloc[-1])
        return {"symbol": normalize_symbol(symbol, "b3"), "last": price, "bid": price, "ask": price, "volume": float(frame["volume"].iloc[-1] or 0.0), "timestamp": datetime.now(timezone.utc).isoformat()}

    async def get_order_book(self, symbol: str, limit: int = 20) -> Dict[str, Any]:
        return {"symbol": normalize_symbol(symbol, "b3"), "bids": [], "asks": [], "limit": limit, "read_only": True}

    async def place_order(self, *args, **kwargs) -> Dict[str, Any]:
        raise MarketConnectorError("B3 Yahoo é somente leitura; configure uma corretora B3 homologada para ordens")

    async def cancel_order(self, *args, **kwargs) -> Dict[str, Any]:
        raise MarketConnectorError("B3 Yahoo é somente leitura")

    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        return {"status": "UNSUPPORTED_READ_ONLY", "order_id": order_id}

    async def get_account_balance(self) -> Dict[str, float]:
        return {}

    async def normalize_order_values(self, symbol: str, quantity: float, price: Optional[float] = None) -> Dict[str, float]:
        result = {"quantity": float(quantity)}
        if price is not None:
            result["price"] = float(price)
        return result


class ForexPublicReadOnlyAdapter:
    """Cotações públicas Forex: forex-python primeiro, Yahoo como fallback."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.is_connected = False
        self.base_url = str(getattr(settings, "YAHOO_FINANCE_BASE_URL", "https://query1.finance.yahoo.com/v8/finance/chart"))
        self.timeout = float(getattr(settings, "NEWS_HTTP_TIMEOUT_SECONDS", 8.0))

    async def connect(self) -> None:
        self.is_connected = True

    async def close(self) -> None:
        self.is_connected = False

    @staticmethod
    def _parts(symbol: str) -> tuple[str, str]:
        normalized = normalize_symbol(symbol, "forex")
        compact = normalized.replace("/", "")
        if len(compact) != 6:
            raise MarketConnectorError(f"par Forex inválido: {symbol}")
        return compact[:3], compact[3:]

    def _yahoo_ticker(self, symbol: str) -> str:
        base, quote = self._parts(symbol)
        return f"{base}{quote}=X"

    def _yahoo_price(self, symbol: str) -> float:
        response = requests.get(
            f"{self.base_url}/{self._yahoo_ticker(symbol)}",
            params={"range": "1d", "interval": "1m"},
            headers={"User-Agent": "ZIA-Trader-readonly/1.0"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        result = response.json().get("chart", {}).get("result", [])
        if not result:
            raise MarketConnectorError("Yahoo não retornou cotação Forex")
        quote = (result[0].get("indicators", {}).get("quote", [{}]) or [{}])[0]
        closes = [float(value) for value in quote.get("close", []) if value is not None]
        if not closes:
            raise MarketConnectorError("Yahoo retornou cotação Forex vazia")
        return closes[-1]

    async def get_market_data(self, symbol: str) -> Dict[str, Any]:
        base, quote = self._parts(symbol)
        price = None
        source = "forex-python"
        try:
            from forex_python.converter import CurrencyRates
            price = float(CurrencyRates().get_rate(base, quote))
        except Exception as exc:
            logger.warning("forex-python indisponível para %s; usando Yahoo: %s", symbol, exc)
            source = "yahoo-finance"
            price = self._yahoo_price(symbol)
        return {
            "symbol": f"{base}/{quote}",
            "last": price,
            "bid": price,
            "ask": price,
            "volume": 0.0,
            "source": source,
            "read_only": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def get_historical_data(self, symbol: str, timeframe: str, limit: int = 100) -> pd.DataFrame:
        if not self.is_connected:
            raise MarketConnectorError("Forex público não está conectado")
        ticker = self._yahoo_ticker(symbol)
        interval = timeframe if timeframe in {"1m", "5m", "15m", "30m", "1h", "1d"} else "1h"
        response = requests.get(
            f"{self.base_url}/{ticker}",
            params={"range": "1y", "interval": interval},
            headers={"User-Agent": "ZIA-Trader-readonly/1.0"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        result = response.json().get("chart", {}).get("result", [])
        if not result:
            raise MarketConnectorError("Yahoo não retornou histórico Forex")
        payload = result[0]
        quote = (payload.get("indicators", {}).get("quote", [{}]) or [{}])[0]
        frame = pd.DataFrame({
            "timestamp": pd.to_datetime(payload.get("timestamp", []), unit="s", utc=True),
            "open": quote.get("open", []),
            "high": quote.get("high", []),
            "low": quote.get("low", []),
            "close": quote.get("close", []),
            "volume": quote.get("volume", []),
        }).dropna(subset=["close"]).tail(max(40, min(int(limit), 1000))).set_index("timestamp")
        if frame.empty:
            raise MarketConnectorError("Yahoo retornou histórico Forex vazio")
        return frame

    async def get_order_book(self, symbol: str, limit: int = 20) -> Dict[str, Any]:
        market = await self.get_market_data(symbol)
        return {"symbol": market["symbol"], "bids": [[market["bid"], 0.0]], "asks": [[market["ask"], 0.0]], "limit": limit, "read_only": True}

    async def place_order(self, *args, **kwargs) -> Dict[str, Any]:
        raise MarketConnectorError("Forex público é somente leitura; configure OANDA/FXCM validado para ordens")

    async def cancel_order(self, *args, **kwargs) -> Dict[str, Any]:
        raise MarketConnectorError("Forex público é somente leitura")

    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        return {"status": "UNSUPPORTED_READ_ONLY", "order_id": order_id}

    async def get_account_balance(self) -> Dict[str, float]:
        return {}

    async def normalize_order_values(self, symbol: str, quantity: float, price: Optional[float] = None) -> Dict[str, float]:
        result = {"quantity": float(quantity)}
        if price is not None:
            result["price"] = float(price)
        return result


class CCXTAdapter:
    """Adapter assíncrono opcional para Spot/Futures, bloqueado sem configuração explícita."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.is_connected = False
        self.exchange = None
        self.market_type = str(getattr(settings, "MARKET_TYPE", "spot")).lower()

    async def connect(self) -> None:
        try:
            import ccxt.async_support as ccxt_async
        except ImportError as exc:
            raise MarketConnectorError("ccxt não está instalado; instale as dependências opcionais") from exc
        exchange_name = str(getattr(self.settings, "CCXT_EXCHANGE_ID", "binance")).lower()
        exchange_class = getattr(ccxt_async, exchange_name, None)
        if exchange_class is None:
            raise MarketConnectorError(f"exchange CCXT não suportada: {exchange_name}")
        options = {"defaultType": self.market_type}
        self.exchange = exchange_class({
            "apiKey": getattr(self.settings, "BINANCE_API_KEY", None),
            "secret": getattr(self.settings, "BINANCE_SECRET_KEY", None),
            "enableRateLimit": True,
            "options": options,
        })
        await self.exchange.load_markets()
        self.is_connected = True

    async def close(self) -> None:
        if self.exchange is not None:
            await self.exchange.close()
        self.is_connected = False

    @staticmethod
    def _ccxt_symbol(symbol: str) -> str:
        value = str(symbol).upper().replace("-", "/")
        if "/" in value:
            return value
        if value.endswith("USDT"):
            return f"{value[:-4]}/USDT"
        return value

    async def get_historical_data(self, symbol: str, timeframe: str, limit: int = 100) -> pd.DataFrame:
        if not self.is_connected or self.exchange is None:
            raise MarketConnectorError("CCXT não está conectado")
        rows = await self.exchange.fetch_ohlcv(self._ccxt_symbol(symbol), timeframe=timeframe, limit=min(int(limit), 1000))
        frame = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
        return frame.set_index("timestamp")

    async def get_market_data(self, symbol: str) -> Dict[str, Any]:
        if not self.is_connected or self.exchange is None:
            raise MarketConnectorError("CCXT não está conectado")
        ticker = await self.exchange.fetch_ticker(self._ccxt_symbol(symbol))
        return {"symbol": symbol, "last": ticker.get("last"), "bid": ticker.get("bid"), "ask": ticker.get("ask"), "volume": ticker.get("baseVolume"), "timestamp": datetime.now(timezone.utc).isoformat()}

    async def get_order_book(self, symbol: str, limit: int = 20) -> Dict[str, Any]:
        if not self.is_connected or self.exchange is None:
            raise MarketConnectorError("CCXT não está conectado")
        return await self.exchange.fetch_order_book(self._ccxt_symbol(symbol), limit=limit)

    async def place_order(self, symbol: str, action: str, order_type: str, quantity: float, price: Optional[float] = None) -> Dict[str, Any]:
        if not bool(getattr(self.settings, "AUTONOMOUS_TRADING_ENABLED", False)):
            raise MarketConnectorError("CCXT live bloqueado: AUTONOMOUS_TRADING_ENABLED=false")
        if bool(getattr(self.settings, "SHADOW_MODE_ENABLED", True)):
            raise MarketConnectorError("CCXT live bloqueado durante shadow mode")
        if not self.is_connected or self.exchange is None:
            raise MarketConnectorError("CCXT não está conectado")
        return await self.exchange.create_order(self._ccxt_symbol(symbol), order_type, action, float(quantity), price)

    async def cancel_order(self, order_id: str, symbol: Optional[str] = None) -> Dict[str, Any]:
        if self.exchange is None:
            raise MarketConnectorError("CCXT não está conectado")
        return await self.exchange.cancel_order(order_id, self._ccxt_symbol(symbol) if symbol else None)

    async def get_order_status(self, order_id: str, symbol: Optional[str] = None) -> Dict[str, Any]:
        if self.exchange is None:
            raise MarketConnectorError("CCXT não está conectado")
        return await self.exchange.fetch_order(order_id, self._ccxt_symbol(symbol) if symbol else None)

    async def get_account_balance(self) -> Dict[str, float]:
        if self.exchange is None:
            raise MarketConnectorError("CCXT não está conectado")
        balance = await self.exchange.fetch_balance()
        return {key: float(value.get("free", 0.0) or 0.0) for key, value in balance.get("total", {}).items() if value is not None}


class MarketConnector:
    """Contrato único de mercado para os serviços do backend."""

    def __init__(self, settings: Settings, exchange_connector: ExchangeConnector | None = None):
        self.settings = settings
        adapter_name = str(getattr(settings, "MARKET_ADAPTER", "binance")).lower()
        market_type = str(getattr(settings, "MARKET_TYPE", "spot")).lower()
        if adapter_name in {"b3", "yahoo", "stocks"}:
            self.market = "b3"
            self._adapter = YahooB3Adapter(settings)
        elif adapter_name in {"forex", "fx"} and str(getattr(settings, "FOREX_MODE", "paper")).lower() in {"public", "readonly", "read_only"}:
            self.market = "forex"
            self._adapter = ForexPublicReadOnlyAdapter(settings)
        elif adapter_name == "ccxt" or (adapter_name == "binance" and market_type == "futures"):
            self.market = "crypto"
            self._adapter = CCXTAdapter(settings)
        else:
            self.market = "forex" if adapter_name in {"forex", "fx"} else "crypto"
            self._adapter = exchange_connector or ExchangeConnector(settings)

    @property
    def market_type(self) -> str:
        return str(getattr(self.settings, "MARKET_TYPE", "spot")).lower()

    @property
    def is_connected(self) -> bool:
        return bool(self._adapter.is_connected)

    def normalize_symbol(self, symbol: str) -> str:
        return normalize_symbol(symbol, self.market)

    def canonical_symbol(self, symbol: str) -> str:
        value = str(symbol or "").strip().upper()
        if self.market == "crypto":
            compact = value.replace("/", "").replace("-", "").replace("_", "")
            return f"{compact[:-4]}/USDT" if compact.endswith("USDT") else value
        return normalize_symbol(value, self.market)

    async def connect(self) -> None:
        await self._adapter.connect()

    async def close(self) -> None:
        await self._adapter.close()

    async def get_historical_data(self, symbol: str, timeframe: str, limit: int = 100) -> pd.DataFrame:
        return await self._adapter.get_historical_data(self.normalize_symbol(symbol), timeframe, limit)

    async def get_market_data(self, symbol: str) -> Dict[str, Any]:
        return await self._adapter.get_market_data(self.normalize_symbol(symbol))

    async def get_order_book(self, symbol: str, limit: int = 20) -> Dict[str, Any]:
        return await self._adapter.get_order_book(self.normalize_symbol(symbol), limit)

    async def normalize_order_values(self, symbol: str, quantity: float, price: Optional[float] = None) -> Dict[str, float]:
        return await self._adapter.normalize_order_values(self.normalize_symbol(symbol), quantity, price)

    async def place_order(self, symbol: str, action: str, order_type: str, quantity: float, price: Optional[float] = None) -> Dict[str, Any]:
        return await self._adapter.place_order(self.normalize_symbol(symbol), action, order_type, quantity, price)

    async def cancel_order(self, order_id: str, symbol: Optional[str] = None) -> Dict[str, Any]:
        if symbol is None:
            return await self._adapter.cancel_order(order_id)
        return await self._adapter.cancel_order(order_id, self.normalize_symbol(symbol))

    async def get_order_status(self, order_id: str, symbol: Optional[str] = None) -> Dict[str, Any]:
        if symbol is None:
            return await self._adapter.get_order_status(order_id)
        return await self._adapter.get_order_status(order_id, self.normalize_symbol(symbol))

    async def get_account_balance(self) -> Dict[str, float]:
        return await self._adapter.get_account_balance()
