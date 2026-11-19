from __future__ import annotations

import asyncio
from types import SimpleNamespace

from core.engine import RoboTraderUnified
from core.sniper_engine import SniperEngine
from execution.order_manager import OrderManager, PendingOrder


class FakeRedis:
    def __init__(self, *, persistent: bool):
        self.is_persistent = persistent


class CountingConnector:
    is_connected = True

    def __init__(self):
        self.calls = []

    def canonical_symbol(self, symbol):
        self.calls.append(("canonical_symbol", symbol))
        return symbol.upper()

    async def get_market_data(self, symbol):
        self.calls.append(("get_market_data", symbol))
        return {"last": 100.0}

    async def get_account_balance(self):
        self.calls.append(("get_account_balance",))
        return {"USDT": 1000.0}

    async def place_order(self, *args, **kwargs):
        self.calls.append(("place_order", args, kwargs))
        return {"status": "success"}


class FakeExecution:
    def __init__(self, redis_cache=None):
        self.redis_cache = redis_cache
        self.db_manager = None
        self.reconciler = None
        self.calls = []

    async def execute_order(self, order):
        self.calls.append(order)
        return {"status": "success"}


def make_settings(**overrides):
    values = {
        "ORDER_MANAGER_MODE": "auto",
        "ORDER_CONFIRMATION_REQUIRED": False,
        "AUTONOMOUS_TRADING_ENABLED": False,
        "REDIS_REQUIRED_FOR_AUTONOMOUS": True,
        "MANUAL_TRADING_ENABLED": False,
        "MARKET_ADAPTER": "binance",
        "MARKET_TYPE": "spot",
        "BINANCE_MODE": "simulated",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def ai_order():
    return {
        "symbol": "BTC/USDT",
        "action": "buy",
        "quantity": 0.01,
        "price": 100.0,
        "signal_validated": True,
    }


def test_order_manager_rechecks_autonomy_after_construction_and_fails_before_adapter_calls():
    settings = make_settings(AUTONOMOUS_TRADING_ENABLED=False)
    redis = FakeRedis(persistent=False)
    connector = CountingConnector()
    manager = OrderManager(settings, connector, FakeExecution(redis))

    settings.AUTONOMOUS_TRADING_ENABLED = True
    result = asyncio.run(
        manager.submit(
            ai_order(),
            source="ai",
            market_context={"trend_alignment": {"passed": True}},
        )
    )

    assert result["status"] == "rejected"
    assert "Redis persistente obrigatório" in result["reason"]
    assert connector.calls == []


def test_persistent_redis_only_removes_autonomy_veto_and_keeps_other_entry_gates():
    settings = make_settings(AUTONOMOUS_TRADING_ENABLED=False)
    redis = FakeRedis(persistent=True)
    connector = CountingConnector()
    manager = OrderManager(settings, connector, FakeExecution(redis))

    settings.AUTONOMOUS_TRADING_ENABLED = True
    result = asyncio.run(manager.submit(ai_order(), source="ai"))

    assert result["status"] == "rejected"
    assert "TrendAlignmentFilter" in result["reason"]
    assert "Redis persistente" not in result["reason"]
    assert connector.calls == [("canonical_symbol", "BTC/USDT")]


def test_missing_redis_fails_closed_for_new_ai_entry():
    settings = make_settings(AUTONOMOUS_TRADING_ENABLED=True)
    connector = CountingConnector()
    manager = OrderManager(settings, connector, FakeExecution(redis_cache=None))

    result = asyncio.run(
        manager.submit(
            ai_order(),
            source="ai",
            market_context={"trend_alignment": {"passed": True}},
        )
    )

    assert result["status"] == "rejected"
    assert "Redis persistente obrigatório" in result["reason"]
    assert connector.calls == []


def test_ai_confirmation_rechecks_autonomy_without_bypassing_signal_gate():
    settings = make_settings(
        AUTONOMOUS_TRADING_ENABLED=False,
        ORDER_CONFIRMATION_REQUIRED=True,
    )
    redis = FakeRedis(persistent=True)
    connector = CountingConnector()
    manager = OrderManager(settings, connector, FakeExecution(redis))
    manager._pending["token"] = PendingOrder(
        token="token",
        order_data={
            "symbol": "BTC/USDT",
            "action": "buy",
            "quantity": 0.01,
            "price": 100.0,
        },
        source="ai",
        market_context={"trend_alignment": {"passed": True}},
        signal_validated=True,
    )

    settings.AUTONOMOUS_TRADING_ENABLED = True
    redis.is_persistent = False
    result = asyncio.run(manager.confirm("token"))

    assert result["status"] == "rejected"
    assert "Redis persistente obrigatório" in result["reason"]
    assert connector.calls == []


def test_engine_autonomy_blocked_property_is_dynamic_not_a_constructor_snapshot():
    settings = make_settings(AUTONOMOUS_TRADING_ENABLED=False)
    redis = FakeRedis(persistent=False)
    engine = object.__new__(RoboTraderUnified)
    engine.settings = settings
    engine.redis_cache = redis

    assert engine.autonomy_blocked is True
    settings.AUTONOMOUS_TRADING_ENABLED = True
    assert engine.autonomy_blocked is True
    redis.is_persistent = True
    assert engine.autonomy_blocked is False


def test_sniper_rechecks_the_same_dynamic_entry_gate():
    settings = make_settings(AUTONOMOUS_TRADING_ENABLED=False)
    redis = FakeRedis(persistent=False)
    execution = SimpleNamespace(redis_cache=redis)
    sniper = object.__new__(SniperEngine)
    sniper.settings = settings
    sniper.execution_engine = execution
    sniper.redis_cache = redis

    settings.AUTONOMOUS_TRADING_ENABLED = True
    assert "Redis persistente obrigatório" in sniper._autonomous_entry_block_reason()
    redis.is_persistent = True
    assert sniper._autonomous_entry_block_reason() is None


def test_sniper_missing_redis_fails_closed_when_required():
    settings = make_settings(AUTONOMOUS_TRADING_ENABLED=True)
    sniper = object.__new__(SniperEngine)
    sniper.settings = settings
    sniper.execution_engine = SimpleNamespace()
    sniper.redis_cache = None

    assert "Redis persistente obrigatório" in sniper._autonomous_entry_block_reason()
