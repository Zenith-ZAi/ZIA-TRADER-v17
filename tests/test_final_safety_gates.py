from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from config.settings import Settings
from core.manager import SniperDisabledError, TradingManager
from database_manager import DatabaseManager
from execution.execution_engine import ExecutionEngine
from execution.order_manager import OrderManager


class FakeRedis:
    def __init__(self):
        self.states = {}

    async def set_state(self, key, value, expire=None):
        self.states[key] = value

    async def get_state(self, key):
        return self.states.get(key)

    async def delete_state(self, key):
        self.states.pop(key, None)


class FakeExchange:
    def __init__(self):
        self.is_connected = True
        self.orders = []
        self.open_orders = []
        self.positions = []

    async def get_open_orders(self):
        return list(self.open_orders)

    async def get_positions(self):
        return list(self.positions)

    async def get_order_by_client_order_id(self, client_order_id, symbol):
        return next((item for item in self.open_orders if item.get("client_order_id") == client_order_id), None)

    async def get_account_balance(self):
        return {"USDT": 10000.0, "BTC": 100.0}

    async def get_market_data(self, symbol):
        return {"symbol": symbol, "last": 100.0, "bid": 99.9, "ask": 100.1}

    def canonical_symbol(self, symbol):
        return symbol.upper()

    async def place_order(self, symbol, action, order_type, quantity, price=None, client_order_id=None):
        order = {
            "symbol": symbol,
            "action": action,
            "order_type": order_type,
            "quantity": float(quantity),
            "price": float(price or 100.0),
            "client_order_id": client_order_id,
        }
        self.orders.append(order)
        return {
            "status": "success",
            "order_id": f"ex-{len(self.orders)}",
            "filled_price": order["price"],
            "filled_quantity": order["quantity"],
            "commission": 0.0,
        }

    async def place_protection_order(self, payload):
        return {"status": "success", "order_id": "protection-1"}

    async def place_oco_orders(self, payload):
        return {"status": "unsupported"}


class WorkerManager:
    def __init__(self, status="ok"):
        self.status = status
        self.redis_cache = SimpleNamespace(is_persistent=True)
        self.exchange_connector = SimpleNamespace(connect=self.connect)
        self.started = []
        self.stopped = False

    async def connect(self):
        return None

    async def reconcile(self):
        return {"status": self.status}

    async def start_trading(self):
        self.started.append("trading")

    async def start_sniper(self):
        self.started.append("sniper")

    async def stop_all(self):
        self.stopped = True


class FakeDatabase:
    def __init__(self):
        self.engine = SimpleNamespace(dispose=lambda: None)

    def create_tables(self):
        return None


def make_order_manager(tmp_path, **overrides):
    values = {
        "DATABASE_URL": f"sqlite:///{tmp_path / 'order-manager.db'}",
        "MARKET_ADAPTER": "binance",
        "BINANCE_MODE": "simulated",
        "ORDER_MANAGER_MODE": "auto",
        "ORDER_CONFIRMATION_REQUIRED": False,
        "AUTONOMOUS_TRADING_ENABLED": True,
        "MANUAL_TRADING_ENABLED": False,
        "LIVE_TRADING_ENABLED": False,
        "LIVE_MODE": False,
        "LIVE_KILL_SWITCH": True,
        "CIRCUIT_BREAKER_ENABLED": False,
    }
    values.update(overrides)
    settings = Settings(**values)
    db = DatabaseManager(settings.DATABASE_URL)
    db.create_tables()
    db.create_or_update_account_state("default_account", 10000.0, 10000.0)
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    db.get_verified_risk_periods = lambda account_id, as_of: {
        "account_id": account_id,
        "source": "equity_ledger_v1",
        "complete": True,
        "fees_included": True,
        "funding_included": True,
        "external_flows_adjusted": True,
        "ledger_consistent": True,
        "updated_at": now.isoformat(),
        "daily": {"period_start": day_start.isoformat(), "starting_equity": 10000.0, "realized_pnl": 0.0, "unrealized_pnl": 0.0},
        "weekly": {"period_start": week_start.isoformat(), "starting_equity": 10000.0, "realized_pnl": 0.0, "unrealized_pnl": 0.0},
        "monthly": {"period_start": month_start.isoformat(), "starting_equity": 10000.0, "realized_pnl": 0.0, "unrealized_pnl": 0.0},
    }
    exchange = FakeExchange()
    redis = FakeRedis()
    execution = ExecutionEngine(settings, exchange, redis, db_manager=db, account_id="default_account")
    manager = OrderManager(settings, exchange, execution)
    return settings, db, exchange, manager


def test_worker_respects_auto_start_false_and_starts_no_engines(monkeypatch):
    import worker

    manager = WorkerManager(status="attention")
    db = FakeDatabase()
    monkeypatch.setattr(worker, "DatabaseManager", lambda *_: db)
    monkeypatch.setattr(worker, "TradingManager", lambda *_: manager)
    monkeypatch.setattr(worker.settings, "AUTO_START_ENGINES", False)
    monkeypatch.setattr(worker.settings, "REQUIRE_PERSISTENT_DATABASE", False)
    monkeypatch.setattr(worker.settings, "REQUIRE_PERSISTENT_REDIS", False)

    asyncio.run(worker.run_worker())

    assert manager.started == []
    assert manager.stopped is True


def test_worker_fails_closed_on_attention_before_auto_start(monkeypatch):
    import worker

    manager = WorkerManager(status="attention")
    db = FakeDatabase()
    monkeypatch.setattr(worker, "DatabaseManager", lambda *_: db)
    monkeypatch.setattr(worker, "TradingManager", lambda *_: manager)
    monkeypatch.setattr(worker.settings, "AUTO_START_ENGINES", True)
    monkeypatch.setattr(worker.settings, "SNIPER_ENABLED", True)
    monkeypatch.setattr(worker.settings, "REQUIRE_PERSISTENT_DATABASE", False)
    monkeypatch.setattr(worker.settings, "REQUIRE_PERSISTENT_REDIS", False)

    with pytest.raises(RuntimeError, match="explicitamente saudável"):
        asyncio.run(worker.run_worker())

    assert manager.started == []
    assert manager.stopped is True


def test_worker_auto_start_obeys_sniper_flag(monkeypatch):
    import worker

    manager = WorkerManager(status="ok")
    db = FakeDatabase()
    monkeypatch.setattr(worker, "DatabaseManager", lambda *_: db)
    monkeypatch.setattr(worker, "TradingManager", lambda *_: manager)
    monkeypatch.setattr(worker.settings, "AUTO_START_ENGINES", True)
    monkeypatch.setattr(worker.settings, "SNIPER_ENABLED", False)
    monkeypatch.setattr(worker.settings, "REQUIRE_PERSISTENT_DATABASE", False)
    monkeypatch.setattr(worker.settings, "REQUIRE_PERSISTENT_REDIS", False)

    asyncio.run(worker.run_worker())

    assert manager.started == ["trading"]
    assert manager.stopped is True


def test_manager_rejects_direct_sniper_start_when_flag_is_off():
    manager = object.__new__(TradingManager)
    manager.settings = SimpleNamespace(SNIPER_ENABLED=False)

    async def should_not_start():
        raise AssertionError("Sniper disabled must not invoke its engine")

    manager.sniper_engine = SimpleNamespace(start=should_not_start)
    with pytest.raises(SniperDisabledError, match="SNIPER_ENABLED=false"):
        asyncio.run(manager.start_sniper())


def test_autonomous_order_requires_internal_validated_signal(tmp_path):
    _, _, exchange, manager = make_order_manager(tmp_path)
    order = {"symbol": "BTC/USDT", "action": "buy", "quantity": 0.01, "price": 100.0, "confidence": 0.95}

    result = asyncio.run(manager.submit(order, source="ai"))

    assert result["status"] == "rejected"
    assert "sinal validada" in result["reason"]
    assert exchange.orders == []


def test_autonomous_order_uses_reconciliation_gate_and_shared_executor(tmp_path):
    _, _, exchange, manager = make_order_manager(tmp_path)
    exchange.open_orders = [{"client_order_id": "untracked-order", "order_id": "remote-1"}]
    order = {
        "symbol": "BTC/USDT",
        "action": "buy",
        "quantity": 0.01,
        "price": 100.0,
        "confidence": 0.95,
        "signal_validated": True,
    }

    result = asyncio.run(manager.submit(order, source="ai"))

    assert result["status"] == "rejected"
    assert "reconciliação" in result["reason"]
    assert exchange.orders == []


def test_manual_confirmation_rechecks_reconciliation_before_sending(tmp_path):
    settings, _, exchange, manager = make_order_manager(
        tmp_path,
        ORDER_MANAGER_MODE="manual",
        ORDER_CONFIRMATION_REQUIRED=True,
        AUTONOMOUS_TRADING_ENABLED=False,
        MANUAL_TRADING_ENABLED=True,
    )
    assert settings.ORDER_CONFIRMATION_REQUIRED is True
    order = {"symbol": "BTC/USDT", "action": "buy", "quantity": 0.01, "price": 100.0}

    pending = asyncio.run(manager.submit(order, source="manual"))
    assert pending["status"] == "pending_confirmation"
    assert exchange.orders == []

    exchange.open_orders = [{"client_order_id": "untracked-order", "order_id": "remote-1"}]
    confirmed = asyncio.run(manager.confirm(pending["confirmation_token"], approved=True))

    assert confirmed["status"] == "rejected"
    assert "reconciliação" in confirmed["reason"]
    assert exchange.orders == []


def test_authorized_autonomous_entry_and_exit_are_centralized(tmp_path):
    _, db, exchange, manager = make_order_manager(tmp_path)
    order = {
        "symbol": "BTC/USDT",
        "action": "buy",
        "quantity": 0.01,
        "price": 100.0,
        "confidence": 0.95,
        "signal_validated": True,
    }
    entered = asyncio.run(manager.submit(order, source="ai"))
    assert entered["status"] == "success"
    assert len(exchange.orders) == 1
    assert len(db.get_open_runtime_positions("default_account")) == 1

    exited = asyncio.run(manager.submit_exit(
        {"symbol": "BTC/USDT", "price": 102.0, "exit_reason": "test_policy"},
        source="ai",
    ))
    assert exited["status"] == "success"
    assert len(exchange.orders) == 2
    assert db.get_open_runtime_positions("default_account") == []


def test_api_rejects_ai_source_and_client_supplied_confirmation(monkeypatch):
    import importlib

    module = importlib.import_module("main")
    with pytest.raises(HTTPException) as raised:
        asyncio.run(module.create_order(
            {"symbol": "BTC/USDT", "action": "buy", "source": "ai", "confirmed": True},
            {"username": "trader", "roles": ["trader"]},
        ))
    assert raised.value.status_code == 400

    monkeypatch.setattr(module.settings, "SNIPER_ENABLED", False)

    async def should_not_start():
        raise AssertionError("disabled Sniper must not start")

    with pytest.raises(HTTPException) as sniper_error:
        asyncio.run(module._start_engine("sniper", should_not_start))
    assert sniper_error.value.status_code == 409
