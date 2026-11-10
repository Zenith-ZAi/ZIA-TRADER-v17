from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from execution.mainnet_adapter import BinanceMainnetAdapter, MainnetDisabledError


class FakeResponse:
    status_code = 200
    headers = {}

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return dict(self.payload)


class FakeSession:
    def __init__(self):
        self.calls = []

    def request(self, method, url, params=None, data=None, headers=None, timeout=None):
        self.calls.append({"method": method, "url": url, "params": params, "data": data})
        return FakeResponse(
            {
                "symbol": "BTCUSDT",
                "orderId": 42,
                "clientOrderId": "intent-safe-1",
                "price": "100",
                "origQty": "0.1",
                "executedQty": "0.1",
                "cummulativeQuoteQty": "10",
                "status": "FILLED",
                "type": "MARKET",
                "side": "BUY",
                "fills": [],
            }
        )

    def close(self):
        return None


def live_settings(**overrides):
    values = {
        "LIVE_KILL_SWITCH": False,
        "LIVE_TRADING_ENABLED": True,
        "LIVE_MODE": True,
        "SHADOW_MODE_ENABLED": False,
        "BINANCE_LIVE_BASE_URL": "https://api.binance.com/api",
        "BINANCE_BASE_URL": "https://api.binance.com/api",
        "BINANCE_MODE": "live",
        "BINANCE_API_KEY": "fake-key",
        "BINANCE_SECRET_KEY": "fake-secret",
        "BINANCE_RECV_WINDOW_MS": 5000,
        "BINANCE_TIMEOUT_SECONDS": 1,
        "HTTP_CONNECT_TIMEOUT_SECONDS": 1,
        "HTTP_READ_TIMEOUT_SECONDS": 1,
        "HTTP_MAX_CONNECTIONS": 2,
        "HTTP_MAX_KEEPALIVE_CONNECTIONS": 1,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def adapter_with_fake_session(settings=None):
    session = FakeSession()
    adapter = BinanceMainnetAdapter(settings or live_settings(), session=session)
    adapter._symbol_filters["BTCUSDT"] = {
        "LOT_SIZE": {"minQty": "0.0001", "stepSize": "0.0001"},
        "PRICE_FILTER": {"tickSize": "0.1"},
        "MIN_NOTIONAL": {"minNotional": "10"},
    }
    return adapter, session


def test_mainnet_adapter_blocks_when_global_kill_switch_is_active():
    adapter, session = adapter_with_fake_session(live_settings(LIVE_KILL_SWITCH=True))

    with pytest.raises(MainnetDisabledError, match="kill switch"):
        asyncio.run(
            adapter.place_order(
                "BTC/USDT", "buy", "market", 0.1, client_order_id="intent-safe-1"
            )
        )

    assert session.calls == []


def test_mainnet_adapter_requires_stable_client_order_id_before_http_send():
    adapter, session = adapter_with_fake_session()

    with pytest.raises(MainnetDisabledError, match="client_order_id"):
        asyncio.run(adapter.place_order("BTC/USDT", "buy", "market", 0.1))

    assert session.calls == []


def test_mainnet_adapter_sends_client_order_id_to_binance_new_client_order_id():
    adapter, session = adapter_with_fake_session()

    result = asyncio.run(
        adapter.place_order(
            "BTC/USDT", "buy", "market", 0.1, client_order_id="intent-safe-1"
        )
    )

    assert result["order_id"] == "42"
    assert len(session.calls) == 1
    assert "newClientOrderId=intent-safe-1" in str(session.calls[0]["data"])
