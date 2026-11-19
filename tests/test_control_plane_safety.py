from __future__ import annotations

import asyncio
from itertools import product
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.runtime_services import health_payload
from cli.runtime_menu import inspect_or_disable_live
from config.settings import Settings
from core.manager import TradingManager
from execution.binance_adapter import BinanceSpotAdapter
from execution.live_authorization import execution_gate_status
from execution.mainnet_adapter import BinanceMainnetAdapter, MainnetDisabledError
from execution.market_connector import MarketConnector, MarketConnectorError


def configuration(**overrides):
    values = dict(MARKET_ADAPTER="binance", MARKET_TYPE="spot", BINANCE_MODE="live",
                  LIVE_TRADING_ENABLED=True, LIVE_MODE=True, LIVE_KILL_SWITCH=False,
                  SHADOW_MODE_ENABLED=False, AUTONOMOUS_TRADING_ENABLED=False,
                  MANUAL_TRADING_ENABLED=False, AUTO_START_ENGINES=False)
    values.update(overrides)
    return SimpleNamespace(**values)


def raw_mainnet(settings=None):
    adapter = object.__new__(BinanceMainnetAdapter)
    adapter.settings = settings or configuration()
    adapter.kill_switch_enabled = False
    return adapter


@pytest.mark.parametrize("kill,enabled,mode", list(product([False, True], repeat=3)))
def test_live_flag_matrix_rechecked_before_every_order_post(monkeypatch, kill, enabled, mode):
    settings = configuration(LIVE_KILL_SWITCH=kill, LIVE_TRADING_ENABLED=enabled, LIVE_MODE=mode)
    adapter = raw_mainnet(settings)
    transport = AsyncMock(return_value={"mock_only": True})
    monkeypatch.setattr(BinanceSpotAdapter, "_request", transport)
    passed = not kill and enabled and mode
    assert execution_gate_status(settings)["live_flags_passed"] is passed
    async def run():
        if passed:
            assert await adapter._request("POST", "/v3/order", {"newClientOrderId": "mock-intent"}, signed=True) == {"mock_only": True}
        else:
            with pytest.raises(MainnetDisabledError):
                await adapter._request("POST", "/v3/order", {"newClientOrderId": "mock-intent"}, signed=True)
    asyncio.run(run())
    assert transport.await_count == int(passed)


def test_protection_rechecks_kill_after_read_only_normalization(monkeypatch):
    adapter = raw_mainnet()
    transport = AsyncMock(return_value={})
    monkeypatch.setattr(BinanceSpotAdapter, "_request", transport)
    async def normalize(*_):
        adapter.settings.LIVE_KILL_SWITCH = True
        return {"quantity": 1, "price": 100}
    adapter.normalize_order_values = normalize
    async def run():
        with pytest.raises(MainnetDisabledError):
            await adapter.place_protection_order({"symbol": "BTC/USDT", "action": "sell", "quantity": 1,
                                                 "limit_price": 100, "stop_price": 90, "client_order_id": "mock-stop"})
    asyncio.run(run())
    transport.assert_not_awaited()


@pytest.mark.parametrize("payload", [{}, {"client_order_id": ""}, {"client_order_id": True}])
def test_protection_requires_id_before_any_normalization(payload):
    adapter = raw_mainnet()
    adapter.normalize_order_values = AsyncMock()
    async def run():
        with pytest.raises(MainnetDisabledError, match="client_order_id"):
            await adapter.place_protection_order(payload)
    asyncio.run(run())
    adapter.normalize_order_values.assert_not_awaited()


def test_local_latch_and_shadow_cannot_bypass_global_post_gate(monkeypatch):
    transport = AsyncMock(return_value={})
    monkeypatch.setattr(BinanceSpotAdapter, "_request", transport)
    adapter = raw_mainnet()
    adapter.activate_kill_switch("mock")
    adapter.deactivate_kill_switch("mock")
    assert adapter.settings.LIVE_KILL_SWITCH is True
    async def run():
        with pytest.raises(MainnetDisabledError):
            await adapter._request("POST", "/v3/order", {"newClientOrderId": "mock"})
        adapter.settings.LIVE_KILL_SWITCH = False
        adapter.settings.SHADOW_MODE_ENABLED = True
        with pytest.raises(MainnetDisabledError):
            await adapter._request("POST", "/v3/order", {"newClientOrderId": "mock"})
    asyncio.run(run())
    transport.assert_not_awaited()


@pytest.mark.parametrize("method", ["place_order", "place_protection_order", "place_oco_orders"])
def test_connector_blocks_live_dispatch_for_every_new_write(method):
    connector = object.__new__(MarketConnector)
    connector.settings = configuration(LIVE_KILL_SWITCH=True)
    connector._adapter = SimpleNamespace(place_order=AsyncMock(), place_protection_order=AsyncMock(), place_oco_orders=AsyncMock())
    connector.normalize_symbol = lambda symbol: symbol
    payload = {"symbol": "BTC/USDT", "action": "sell", "quantity": 1, "client_order_id": "mock"}
    async def run():
        with pytest.raises(MarketConnectorError):
            if method == "place_order":
                await connector.place_order("BTC/USDT", "buy", "market", 1, client_order_id="mock")
            else:
                await getattr(connector, method)(payload)
    asyncio.run(run())
    for name in ["place_order", "place_protection_order", "place_oco_orders"]:
        getattr(connector._adapter, name).assert_not_awaited()


def test_menu_can_disarm_invalid_live_combination_but_cannot_enable_live():
    settings = configuration(LIVE_TRADING_ENABLED=False, LIVE_MODE=True)
    assert inspect_or_disable_live(settings)["action"] == "live_disabled_locally"
    assert settings.LIVE_MODE is False and settings.LIVE_KILL_SWITCH is True
    settings.LIVE_TRADING_ENABLED = True
    assert inspect_or_disable_live(settings)["action"] == "live_activation_not_supported_by_menu"
    assert settings.LIVE_MODE is False and settings.LIVE_KILL_SWITCH is True


def test_manager_and_health_show_actual_requested_flags_not_hardcoded_live_false():
    settings = Settings(_env_file=None, BINANCE_MODE="live", LIVE_TRADING_ENABLED=True, LIVE_MODE=True,
                        LIVE_KILL_SWITCH=True, SHADOW_MODE_ENABLED=True, MANUAL_TRADING_ENABLED=True)
    manager = SimpleNamespace(settings=settings, runtime_profile={},
                              order_manager=SimpleNamespace(mode="manual", confirmation_required=True),
                              market_connector=SimpleNamespace(market_type="spot"),
                              daily_state=SimpleNamespace(status=lambda: {}),
                              redis_cache=SimpleNamespace(health=lambda: {"persistent": False}),
                              news_processor=SimpleNamespace(health=lambda: {}),
                              exchange_connector=SimpleNamespace(is_connected=False))
    status = TradingManager.runtime_status(manager)
    assert status["settings"]["live_trading_enabled"] is True
    assert status["settings"]["manual_trading_enabled"] is True
    assert status["execution_gates"]["live_flags_passed"] is False
    db = SimpleNamespace(engine=MagicMock(), get_ai_observations=lambda **_: [])
    app = SimpleNamespace(state=SimpleNamespace(settings=settings, engine_tasks={},
                          runtime=SimpleNamespace(db_manager=db, trading_manager=manager)))
    health = health_payload(app)
    assert health["live_trading_enabled"] is True and health["live_mode"] is True
    assert health["execution_gates"]["live_kill_switch"] is True
    assert health["execution_gates"]["live_flags_passed"] is False


def test_missing_connector_configuration_is_fail_closed():
    connector = object.__new__(MarketConnector)
    connector._adapter = SimpleNamespace(place_order=AsyncMock())
    async def run():
        with pytest.raises(MarketConnectorError, match="configuração.*ausente"):
            await connector.place_order("BTC/USDT", "buy", "market", 1, client_order_id="mock")
    asyncio.run(run())
    connector._adapter.place_order.assert_not_awaited()


@pytest.mark.parametrize("environment", ["development", "staging", "production"])
def test_live_restart_cannot_auto_rearm_in_any_environment(environment):
    from config.startup_validation import validate_startup_configuration
    settings = configuration(AUTO_START_ENGINES=True, ENVIRONMENT=environment)
    with pytest.raises(RuntimeError, match="autostart live bloqueado"):
        validate_startup_configuration(settings)
