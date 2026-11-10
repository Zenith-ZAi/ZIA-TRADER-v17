from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from execution.exchange_connector import ExchangeConnector
from execution.live_authorization import (
    live_submission_block_reason,
    requires_live_authorization,
)
from execution.market_connector import CCXTAdapter, MarketConnector, MarketConnectorError
from execution.mt5_adapter import MetaTrader5Adapter
from execution.order_manager import OrderManager


def settings(**overrides):
    values = {
        "MARKET_ADAPTER": "binance",
        "MARKET_TYPE": "spot",
        "BINANCE_MODE": "simulated",
        "FOREX_MODE": "paper",
        "LIVE_KILL_SWITCH": True,
        "LIVE_TRADING_ENABLED": False,
        "LIVE_MODE": False,
        "AUTONOMOUS_TRADING_ENABLED": False,
        "MANUAL_TRADING_ENABLED": False,
        "SHADOW_MODE_ENABLED": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.parametrize(
    "configuration",
    [
        {"MARKET_ADAPTER": "mt5"},
        {"MARKET_ADAPTER": "ccxt"},
        {"MARKET_ADAPTER": "binance", "MARKET_TYPE": "futures"},
        {"MARKET_ADAPTER": "fix"},
        {"MARKET_ADAPTER": "unrecognized-adapter"},
    ],
)
def test_transacting_or_unknown_adapters_require_live_authorization(configuration):
    assert requires_live_authorization(settings(**configuration)) is True


def test_known_read_only_and_simulated_adapters_do_not_require_live_authorization():
    assert requires_live_authorization(settings(MARKET_ADAPTER="stocks")) is False
    assert requires_live_authorization(settings(MARKET_ADAPTER="forex", FOREX_MODE="public")) is False
    assert requires_live_authorization(settings()) is False


def test_live_authorization_requires_all_three_flags():
    assert "kill switch" in live_submission_block_reason(settings())
    assert live_submission_block_reason(
        settings(LIVE_KILL_SWITCH=False, LIVE_TRADING_ENABLED=True, LIVE_MODE=False)
    ) == "LIVE_MODE não autorizado"
    assert live_submission_block_reason(
        settings(LIVE_KILL_SWITCH=False, LIVE_TRADING_ENABLED=True, LIVE_MODE=True)
    ) is None


@pytest.mark.parametrize("adapter", ["mt5", "ccxt"])
def test_order_manager_fails_closed_for_live_capable_adapters(adapter):
    manager = object.__new__(OrderManager)
    manager.settings = settings(
        MARKET_ADAPTER=adapter,
        ORDER_MANAGER_MODE="manual",
        MANUAL_TRADING_ENABLED=True,
    )
    manager.mode = "manual"

    reason = manager._authorized("manual", {"symbol": "EURUSD", "action": "buy"})

    assert reason is not None
    assert "kill switch" in reason


def test_ccxt_cannot_call_exchange_without_global_live_authorization():
    calls = []

    class FakeExchange:
        async def create_order(self, *args, **kwargs):
            calls.append((args, kwargs))
            return {"id": "unexpected"}

    adapter = CCXTAdapter(
        settings(
            MARKET_ADAPTER="ccxt",
            AUTONOMOUS_TRADING_ENABLED=True,
            SHADOW_MODE_ENABLED=False,
        )
    )
    adapter.is_connected = True
    adapter.exchange = FakeExchange()

    with pytest.raises(MarketConnectorError, match="kill switch"):
        asyncio.run(adapter.place_order("BTC/USDT", "buy", "market", 0.01))

    assert calls == []


def test_mt5_cannot_call_order_send_without_global_live_authorization():
    calls = []

    class FakeMT5:
        def order_send(self, request):
            calls.append(request)
            return SimpleNamespace(retcode=0)

    adapter = MetaTrader5Adapter(settings(MARKET_ADAPTER="mt5"))
    adapter.is_connected = True
    adapter._mt5 = FakeMT5()

    with pytest.raises(RuntimeError, match="kill switch"):
        asyncio.run(adapter.place_order("EURUSD", "buy", "market", 1.0))

    assert calls == []


@pytest.mark.parametrize("adapter_name", ["ccxt", "mt5"])
def test_unaudited_adapters_remain_disabled_even_if_live_flags_are_enabled(adapter_name):
    live_settings = settings(
        MARKET_ADAPTER=adapter_name,
        LIVE_KILL_SWITCH=False,
        LIVE_TRADING_ENABLED=True,
        LIVE_MODE=True,
        AUTONOMOUS_TRADING_ENABLED=True,
        SHADOW_MODE_ENABLED=False,
    )
    if adapter_name == "ccxt":
        adapter = CCXTAdapter(live_settings)
        adapter.is_connected = True
        adapter.exchange = SimpleNamespace(
            create_order=lambda *_args, **_kwargs: pytest.fail("external CCXT call must remain blocked")
        )
        error_type = MarketConnectorError
    else:
        adapter = MetaTrader5Adapter(live_settings)
        adapter.is_connected = True
        adapter._mt5 = SimpleNamespace(
            order_send=lambda *_args: pytest.fail("MT5 order_send must remain blocked")
        )
        error_type = RuntimeError

    with pytest.raises(error_type, match="desabilitado"):
        asyncio.run(
            adapter.place_order(
                "BTC/USDT", "buy", "market", 0.01, client_order_id="intent-123"
            )
        )


@pytest.mark.parametrize("connector_type", ["exchange", "market"])
def test_connectors_never_retry_after_adapter_type_error(connector_type):
    calls = []

    class AdapterWithInternalTypeError:
        async def place_order(
            self, symbol, action, order_type, quantity, price=None, client_order_id=None
        ):
            calls.append(client_order_id)
            raise TypeError("internal adapter bug after entry")

    adapter = AdapterWithInternalTypeError()
    if connector_type == "exchange":
        connector = object.__new__(ExchangeConnector)
        connector._adapter = adapter
    else:
        connector = object.__new__(MarketConnector)
        connector._adapter = adapter
        connector.market = "crypto"

    with pytest.raises(TypeError, match="internal adapter bug"):
        asyncio.run(
            connector.place_order(
                "BTC/USDT", "buy", "market", 0.01, client_order_id="intent-123"
            )
        )

    assert calls == ["intent-123"]


@pytest.mark.parametrize("connector_type", ["exchange", "market"])
def test_connectors_reject_adapter_without_explicit_idempotency_contract(connector_type):
    calls = []

    class AdapterWithoutId:
        async def place_order(self, symbol, action, order_type, quantity, price=None):
            calls.append(symbol)
            return {"status": "success"}

    adapter = AdapterWithoutId()
    if connector_type == "exchange":
        connector = object.__new__(ExchangeConnector)
        connector._adapter = adapter
        expected_exception = RuntimeError
    else:
        connector = object.__new__(MarketConnector)
        connector._adapter = adapter
        connector.market = "crypto"
        expected_exception = MarketConnectorError

    with pytest.raises(expected_exception, match="client_order_id"):
        asyncio.run(
            connector.place_order(
                "BTC/USDT", "buy", "market", 0.01, client_order_id="intent-123"
            )
        )

    assert calls == []
