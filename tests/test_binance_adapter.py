import asyncio

import pytest

from config.settings import Settings
from execution.binance_adapter import BinanceAdapterError, BinanceSpotAdapter


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.headers = {}

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self):
        self.calls = []

    def request(self, method, url, params=None, data=None, headers=None, timeout=None):
        self.calls.append({"method": method, "url": url, "params": params, "data": data, "headers": headers, "timeout": timeout})
        if url.endswith("/v3/time"):
            return FakeResponse({"serverTime": 1700000000000})
        if url.endswith("/v3/exchangeInfo"):
            return FakeResponse({
                "symbols": [{
                    "symbol": "BTCUSDT",
                    "filters": [
                        {"filterType": "LOT_SIZE", "minQty": "0.0001", "stepSize": "0.0001"},
                        {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
                        {"filterType": "MIN_NOTIONAL", "minNotional": "10"},
                    ],
                }]
            })
        if url.endswith("/v3/account"):
            return FakeResponse({"balances": [{"asset": "USDT", "free": "1000", "locked": "0"}]})
        if url.endswith("/v3/ticker/24hr"):
            return FakeResponse({"lastPrice": "50000", "volume": "123"})
        if url.endswith("/v3/ticker/bookTicker"):
            return FakeResponse({"bidPrice": "49999", "askPrice": "50001"})
        if url.endswith("/v3/klines"):
            return FakeResponse([[1700000000000, "1", "2", "0.5", "1.5", "10", 1700000060000, "15", 2, "5", "7", "0"]])
        return FakeResponse({})

    def close(self):
        return None


def sandbox_settings(**overrides):
    values = {
        "BINANCE_MODE": "testnet",
        "BINANCE_BASE_URL": "https://testnet.binance.vision/api",
        "BINANCE_API_KEY": "test-key",
        "BINANCE_SECRET_KEY": "test-secret",
    }
    values.update(overrides)
    return Settings(**values)


def test_adapter_rejects_production_host():
    with pytest.raises(BinanceAdapterError):
        BinanceSpotAdapter(sandbox_settings(BINANCE_BASE_URL="https://api.binance.com/api"))


def test_adapter_connect_market_balance_history_and_filters():
    session = FakeSession()
    adapter = BinanceSpotAdapter(sandbox_settings(), session=session)
    asyncio.run(adapter.connect())
    assert adapter.is_connected is True

    market = asyncio.run(adapter.get_market_data("BTC/USDT"))
    assert market["last"] == 50000.0
    assert market["bid"] < market["ask"]

    history = asyncio.run(adapter.get_historical_data("BTC/USDT", "1m", 1))
    assert list(history.columns) == ["open", "high", "low", "close", "volume"]
    assert len(history) == 1

    balance = asyncio.run(adapter.get_account_balance())
    assert balance == {"USDT": 1000.0}

    normalized = asyncio.run(adapter.normalize_order_values("BTC/USDT", 0.00127, 50000.019))
    assert normalized == {"quantity": 0.0012, "price": 50000.0}

    signed_call = next(call for call in session.calls if call["url"].endswith("/v3/account"))
    signed_query = signed_call["params"] or ""
    assert "signature=" in signed_query
    assert "test-secret" not in signed_query


def test_adapter_aggregates_supported_10m_from_5m():
    session = FakeSession()
    adapter = BinanceSpotAdapter(sandbox_settings(), session=session)
    history = asyncio.run(adapter.get_historical_data("BTC/USDT", "10m", 1))
    assert len(history) == 1
    kline_call = next(call for call in session.calls if call["url"].endswith("/v3/klines"))
    assert "interval=5m" in str(kline_call["params"])
