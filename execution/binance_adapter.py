"""Adapter HTTP assinado para Binance Spot Testnet/Demo.

O módulo não habilita produção. A seleção segura é feita pelo ExchangeConnector:
`BINANCE_MODE=testnet` ou `BINANCE_MODE=demo` exigem hosts sandbox conhecidos.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urlencode, urlparse

import httpx
import pandas as pd

from config.settings import Settings

logger = logging.getLogger(__name__)


class BinanceAdapterError(RuntimeError):
    """Erro de transporte, autenticação, limite ou resposta da Binance."""


class BinanceRateLimitError(BinanceAdapterError):
    """A API respondeu com limite de requisições."""


class BinanceAuthenticationError(BinanceAdapterError):
    """Credencial, assinatura, permissão ou relógio rejeitado pela API."""


class BinanceSpotAdapter:
    """Implementação real da API Spot somente em ambiente Testnet/Demo."""

    ALLOWED_HOSTS = {"testnet.binance.vision", "demo-api.binance.com"}
    INTERVALS = {"1m", "3m", "5m", "10m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M"}

    def __init__(self, settings: Settings, session: Optional[Any] = None):
        self.settings = settings
        self.api_key = settings.BINANCE_API_KEY
        self.secret_key = settings.BINANCE_SECRET_KEY
        self.base_url = self._normalize_base_url(settings.BINANCE_BASE_URL)
        self.session = session
        self.http_client = None if session is not None else httpx.AsyncClient(
            timeout=httpx.Timeout(
                timeout=float(getattr(settings, "BINANCE_TIMEOUT_SECONDS", 10.0)),
                connect=float(getattr(settings, "HTTP_CONNECT_TIMEOUT_SECONDS", 5.0)),
                read=float(getattr(settings, "HTTP_READ_TIMEOUT_SECONDS", 15.0)),
                write=float(getattr(settings, "HTTP_READ_TIMEOUT_SECONDS", 15.0)),
                pool=float(getattr(settings, "HTTP_CONNECT_TIMEOUT_SECONDS", 5.0)),
            ),
            limits=httpx.Limits(
                max_connections=int(getattr(settings, "HTTP_MAX_CONNECTIONS", 50)),
                max_keepalive_connections=int(getattr(settings, "HTTP_MAX_KEEPALIVE_CONNECTIONS", 20)),
            ),
            follow_redirects=False,
        )
        self.is_connected = False
        self.server_time_offset_ms = 0
        self.exchange_info: Dict[str, Any] = {}
        self._symbol_filters: Dict[str, Dict[str, Dict[str, str]]] = {}
        self._order_symbols: Dict[str, str] = {}
        self._validate_configuration()

    @classmethod
    def _normalize_base_url(cls, value: str) -> str:
        parsed = urlparse(value.strip())
        if parsed.scheme != "https" or parsed.hostname not in cls.ALLOWED_HOSTS:
            raise BinanceAdapterError(
                "BINANCE_BASE_URL deve apontar para testnet.binance.vision ou demo-api.binance.com em HTTPS."
            )
        path = parsed.path.rstrip("/")
        if not path.endswith("/api"):
            path = f"{path}/api" if path else "/api"
        return f"{parsed.scheme}://{parsed.netloc}{path}"

    def _validate_configuration(self) -> None:
        mode = self.settings.BINANCE_MODE.lower()
        host = urlparse(self.base_url).hostname
        if not self.api_key or not self.secret_key:
            raise BinanceAdapterError("BINANCE_API_KEY e BINANCE_SECRET_KEY são obrigatórias no modo sandbox.")
        if mode not in {"testnet", "demo"}:
            raise BinanceAdapterError("O adapter real só pode ser usado com BINANCE_MODE=testnet ou BINANCE_MODE=demo.")
        expected_host = "testnet.binance.vision" if mode == "testnet" else "demo-api.binance.com"
        if host != expected_host:
            raise BinanceAdapterError(f"BINANCE_MODE={mode} exige BINANCE_BASE_URL no host {expected_host}.")

    @staticmethod
    def symbol_code(symbol: str) -> str:
        return str(symbol).replace("/", "").replace("-", "").upper()

    def _timestamp(self) -> int:
        return int(time.time() * 1000) + self.server_time_offset_ms

    def _signed_query(self, params: Dict[str, Any]) -> str:
        ordered = {key: value for key, value in params.items() if value is not None}
        query = urlencode(ordered, doseq=True)
        signature = hmac.new(self.secret_key.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{query}&signature={signature}"

    @staticmethod
    def _parse_response(response: Any) -> Any:
        if response.status_code in {418, 429}:
            retry_after = response.headers.get("Retry-After", "unknown")
            raise BinanceRateLimitError(f"Binance rate limit status={response.status_code}; retry_after={retry_after}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise BinanceAdapterError(f"Resposta Binance não é JSON: HTTP {response.status_code}") from exc
        return payload

    def _validate_payload(self, response: Any, payload: Any) -> Any:
        if response.status_code >= 400 or (isinstance(payload, dict) and payload.get("code", 0) < 0):
            code = payload.get("code") if isinstance(payload, dict) else response.status_code
            message = payload.get("msg") if isinstance(payload, dict) else str(payload)
            if code in {-2015, -2014, -1022, -1021}:
                raise BinanceAuthenticationError(
                    f"Binance authentication error code={code}: {message}. "
                    "Confirme que a chave foi criada no Spot Testnet/Demo correto, "
                    "que USER_DATA está permitido, TRADE só é habilitado se necessário, "
                    "e que a whitelist de IP não bloqueia este servidor."
                )
            raise BinanceAdapterError(f"Binance error code={code}: {message}")
        return payload

    def _request_legacy_session(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        signed: bool = False,
    ) -> Any:
        params = dict(params or {})
        headers = {"X-MBX-APIKEY": self.api_key} if self.api_key else {}
        if signed:
            params.setdefault("timestamp", self._timestamp())
            params.setdefault("recvWindow", self.settings.BINANCE_RECV_WINDOW_MS)
            query = self._signed_query(params)
        else:
            query = urlencode({key: value for key, value in params.items() if value is not None}, doseq=True)
        url = f"{self.base_url}{path}"
        is_body_method = method.upper() in {"POST", "DELETE"}
        response = self.session.request(
            method.upper(),
            url,
            params=None if is_body_method else query,
            data=query if is_body_method else None,
            headers=headers,
            timeout=self.settings.BINANCE_TIMEOUT_SECONDS,
        )
        payload = self._parse_response(response)
        return self._validate_payload(response, payload)

    async def _request(self, method: str, path: str, params: Optional[Dict[str, Any]] = None, signed: bool = False) -> Any:
        params = dict(params or {})
        headers = {"X-MBX-APIKEY": self.api_key} if self.api_key else {}
        if signed:
            params.setdefault("timestamp", self._timestamp())
            params.setdefault("recvWindow", self.settings.BINANCE_RECV_WINDOW_MS)
            query = self._signed_query(params)
        else:
            query = urlencode({key: value for key, value in params.items() if value is not None}, doseq=True)
        url = f"{self.base_url}{path}"
        is_body_method = method.upper() in {"POST", "DELETE"}
        if self.session is not None:
            # Compatibilidade exclusiva com FakeSession em testes; produção usa httpx.AsyncClient.
            return await asyncio.to_thread(self._request_legacy_session, method, path, params, signed)
        response = await self.http_client.request(
            method.upper(),
            url,
            params=None if is_body_method else query,
            content=query if is_body_method else None,
            headers=headers,
        )
        payload = self._parse_response(response)
        return self._validate_payload(response, payload)

    async def connect(self) -> None:
        server_time = await self._request("GET", "/v3/time")
        self.server_time_offset_ms = int(server_time["serverTime"]) - int(time.time() * 1000)
        if self.settings.BINANCE_PRELOAD_EXCHANGE_INFO:
            self.exchange_info = await self._request("GET", "/v3/exchangeInfo")
            self._index_filters(self.exchange_info)
        self.is_connected = True
        logger.info("Binance Spot conectado em modo %s: %s", self.settings.BINANCE_MODE, self.base_url)

    async def close(self) -> None:
        if self.session is not None and hasattr(self.session, "close"):
            self.session.close()
        if self.http_client is not None:
            await self.http_client.aclose()
        self.is_connected = False

    def _index_filters(self, payload: Dict[str, Any]) -> None:
        self._symbol_filters = {}
        for symbol in payload.get("symbols", []):
            code = symbol.get("symbol", "")
            self._symbol_filters[code] = {
                item.get("filterType", ""): item for item in symbol.get("filters", [])
            }

    async def _ensure_filters(self, symbol: str) -> Dict[str, Dict[str, str]]:
        code = self.symbol_code(symbol)
        if not self._symbol_filters:
            self.exchange_info = await self._request("GET", "/v3/exchangeInfo", {"symbol": code})
            self._index_filters(self.exchange_info)
        filters = self._symbol_filters.get(code)
        if not filters:
            raise BinanceAdapterError(f"Símbolo não encontrado na Binance sandbox: {code}")
        return filters

    @staticmethod
    def _floor_step(value: float, step: str) -> float:
        if not step or Decimal(step) == 0:
            return float(value)
        decimal_value = Decimal(str(value))
        decimal_step = Decimal(step)
        return float((decimal_value / decimal_step).to_integral_value(rounding=ROUND_DOWN) * decimal_step)

    async def normalize_order_values(self, symbol: str, quantity: float, price: Optional[float] = None) -> Dict[str, float]:
        filters = await self._ensure_filters(symbol)
        lot = filters.get("LOT_SIZE", {})
        price_filter = filters.get("PRICE_FILTER", {})
        normalized_quantity = self._floor_step(quantity, lot.get("stepSize", "0"))
        normalized_price = None if price is None else self._floor_step(price, price_filter.get("tickSize", "0"))
        min_qty = float(lot.get("minQty", "0"))
        if normalized_quantity < min_qty:
            raise BinanceAdapterError(f"Quantidade {normalized_quantity} abaixo de minQty {min_qty} para {symbol}")
        notional = filters.get("MIN_NOTIONAL") or filters.get("NOTIONAL") or {}
        if normalized_price is not None and normalized_price * normalized_quantity < float(notional.get("minNotional", "0")):
            raise BinanceAdapterError(f"Notional abaixo do mínimo da Binance para {symbol}")
        result = {"quantity": normalized_quantity}
        if normalized_price is not None:
            result["price"] = normalized_price
        return result

    @staticmethod
    def _klines_to_frame(payload: list) -> pd.DataFrame:
        columns = ["timestamp", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "trades", "taker_base", "taker_quote", "ignore"]
        frame = pd.DataFrame(payload, columns=columns)
        if frame.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
        for column in ["open", "high", "low", "close", "volume"]:
            frame[column] = pd.to_numeric(frame[column], errors="raise")
        return frame.set_index("timestamp")[["open", "high", "low", "close", "volume"]].sort_index()

    async def get_historical_data(self, symbol: str, timeframe: str, limit: int = 100) -> pd.DataFrame:
        if timeframe not in self.INTERVALS:
            raise BinanceAdapterError(f"Timeframe não suportado pela Binance: {timeframe}")
        if timeframe == "10m":
            source_limit = min(max(int(limit) * 2 + 2, 10), 1000)
            payload = await self._request(
                "GET",
                "/v3/klines",
                {"symbol": self.symbol_code(symbol), "interval": "5m", "limit": source_limit},
            )
            frame = self._klines_to_frame(payload)
            if frame.empty:
                return frame
            aggregated = frame.resample("10min", label="left", closed="left").agg(
                {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
            ).dropna()
            return aggregated.tail(int(limit))
        payload = await self._request(
            "GET",
            "/v3/klines",
            {"symbol": self.symbol_code(symbol), "interval": timeframe, "limit": min(limit, 1000)},
        )
        return self._klines_to_frame(payload)

    async def get_market_data(self, symbol: str) -> Dict[str, Any]:
        code = self.symbol_code(symbol)
        ticker, book = await asyncio.gather(
            self._request("GET", "/v3/ticker/24hr", {"symbol": code}),
            self._request("GET", "/v3/ticker/bookTicker", {"symbol": code}),
        )
        return {
            "symbol": symbol,
            "last": float(ticker["lastPrice"]),
            "bid": float(book["bidPrice"]),
            "ask": float(book["askPrice"]),
            "volume": float(ticker["volume"]),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def get_order_book(self, symbol: str, limit: int = 20) -> Dict[str, Any]:
        payload = await self._request(
            "GET",
            "/v3/depth",
            {"symbol": self.symbol_code(symbol), "limit": min(max(int(limit), 5), 1000)},
        )

        def levels(values):
            return [
                {"price": float(price), "quantity": float(quantity), "notional": float(price) * float(quantity)}
                for price, quantity in values
            ]

        return {"symbol": symbol, "bids": levels(payload.get("bids", [])), "asks": levels(payload.get("asks", [])), "last_update_id": payload.get("lastUpdateId")}

    async def place_order(self, symbol: str, action: str, order_type: str, quantity: float, price: Optional[float] = None, client_order_id: Optional[str] = None) -> Dict[str, Any]:
        code = self.symbol_code(symbol)
        side = action.upper()
        if side not in {"BUY", "SELL"}:
            raise BinanceAdapterError(f"Ação inválida: {action}")
        normalized = await self.normalize_order_values(symbol, quantity, price if order_type.lower() == "limit" else None)
        params: Dict[str, Any] = {
            "symbol": code,
            "side": side,
            "type": order_type.upper(),
            "quantity": normalized["quantity"],
            "newClientOrderId": client_order_id,
            "newOrderRespType": "RESULT",
        }
        if order_type.lower() == "limit":
            if price is None:
                raise BinanceAdapterError("Ordem LIMIT exige price")
            params.update({"timeInForce": "GTC", "price": normalized["price"]})
        payload = await self._request("POST", "/v3/order", params, signed=True)
        order_id = str(payload["orderId"])
        self._order_symbols[order_id] = code
        executed_qty = float(payload.get("executedQty", 0.0))
        quote_qty = float(payload.get("cummulativeQuoteQty", 0.0))
        return {
            "status": "success" if payload.get("status") not in {"REJECTED", "EXPIRED"} else "failed",
            "order_id": order_id,
            "symbol": symbol,
            "action": action.lower(),
            "order_type": order_type.lower(),
            "filled_price": quote_qty / executed_qty if executed_qty else float(price or 0.0),
            "filled_quantity": executed_qty,
            "commission": sum(float(fill.get("commission", 0.0)) for fill in payload.get("fills", [])),
            "exchange_status": payload.get("status"),
            "raw": payload,
        }

    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        code = self._order_symbols.get(str(order_id))
        if not code:
            raise BinanceAdapterError("Símbolo da ordem desconhecido; mantenha o mapeamento da ordem no storage.")
        payload = await self._request("DELETE", "/v3/order", {"symbol": code, "orderId": order_id}, signed=True)
        return {"status": "success", "order_id": str(payload.get("orderId", order_id)), "exchange_status": payload.get("status"), "raw": payload}

    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        code = self._order_symbols.get(str(order_id))
        if not code:
            raise BinanceAdapterError("Símbolo da ordem desconhecido; mantenha o mapeamento da ordem no storage.")
        payload = await self._request("GET", "/v3/order", {"symbol": code, "orderId": order_id}, signed=True)
        return {"status": payload.get("status", "UNKNOWN"), "order_id": str(payload.get("orderId", order_id)), "raw": payload}

    async def get_open_orders(self) -> list[Dict[str, Any]]:
        payload = await self._request("GET", "/v3/openOrders", signed=True)
        return [
            {
                "order_id": str(item.get("orderId")),
                "client_order_id": item.get("clientOrderId"),
                "symbol": item.get("symbol"),
                "status": str(item.get("status", "UNKNOWN")).lower(),
                "side": str(item.get("side", "")).lower(),
                "orig_qty": float(item.get("origQty", 0.0)),
                "executed_qty": float(item.get("executedQty", 0.0)),
            }
            for item in payload
        ]

    async def get_positions(self) -> list[Dict[str, Any]]:
        balances = await self.get_account_balance()
        return [{"symbol": asset, "quantity": quantity} for asset, quantity in balances.items() if quantity > 0]

    async def place_protection_order(self, protection: Dict[str, Any]) -> Dict[str, Any]:
        code = self.symbol_code(protection["symbol"])
        normalized = await self.normalize_order_values(protection["symbol"], protection["quantity"], protection.get("limit_price"))
        params: Dict[str, Any] = {
            "symbol": code,
            "side": str(protection["action"]).upper(),
            "type": str(protection.get("order_type", "STOP_LOSS_LIMIT")).upper(),
            "quantity": normalized["quantity"],
            "price": normalized.get("price", protection.get("limit_price")),
            "stopPrice": protection.get("stop_price"),
            "timeInForce": "GTC",
            "newClientOrderId": protection.get("client_order_id"),
            "newOrderRespType": "RESULT",
        }
        payload = await self._request("POST", "/v3/order", params, signed=True)
        order_id = str(payload["orderId"])
        self._order_symbols[order_id] = code
        executed_qty = float(payload.get("executedQty", 0.0))
        quote_qty = float(payload.get("cummulativeQuoteQty", 0.0))
        return {
            "status": "success" if payload.get("status") not in {"REJECTED", "EXPIRED"} else "failed",
            "order_id": order_id,
            "client_order_id": payload.get("clientOrderId") or protection.get("client_order_id"),
            "filled_price": quote_qty / executed_qty if executed_qty else float(protection.get("limit_price") or protection.get("stop_price") or 0.0),
            "filled_quantity": executed_qty,
            "exchange_status": payload.get("status"),
            "raw": payload,
        }

    async def get_account_balance(self) -> Dict[str, float]:
        payload = await self._request("GET", "/v3/account", signed=True)
        return {
            item["asset"]: float(item.get("free", 0.0)) + float(item.get("locked", 0.0))
            for item in payload.get("balances", [])
            if float(item.get("free", 0.0)) + float(item.get("locked", 0.0)) > 0
        }
