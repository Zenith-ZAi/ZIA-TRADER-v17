import asyncio

import numpy as np
import pandas as pd
import pytest

from config.settings import Settings
from core.pre_market_gate import PreMarketGate
from execution.market_connector import MarketConnector, MarketConnectorError
from execution.order_manager import OrderManager
from risk.adaptive_kelly import AdaptiveKellySizer


class FakeExecution:
    db_manager = None

    async def execute_order(self, order):
        return {"status": "success", "order_id": "fake-1", "filled_price": order.get("price", 1.0), "filled_quantity": order["quantity"]}


def test_market_connector_normalizes_symbols_and_keeps_b3_read_only():
    crypto = MarketConnector(Settings(MARKET_ADAPTER="binance", BINANCE_MODE="simulated"))
    assert crypto.normalize_symbol("BTC/USDT") == "BTCUSDT"
    assert crypto.canonical_symbol("BTCUSDT") == "BTC/USDT"
    forex = MarketConnector(Settings(MARKET_ADAPTER="forex", FOREX_MODE="paper"))
    assert forex.normalize_symbol("EURUSD") == "EUR/USD"
    b3 = MarketConnector(Settings(MARKET_ADAPTER="b3"))
    assert b3.normalize_symbol("PETR4") == "PETR4.SA"
    with pytest.raises(MarketConnectorError):
        asyncio.run(b3.place_order("PETR4", "buy", "market", 1))


def test_order_manager_requires_visual_confirmation(monkeypatch):
    settings = Settings(
        MARKET_ADAPTER="forex", FOREX_MODE="paper", ORDER_MANAGER_MODE="manual",
        ORDER_CONFIRMATION_REQUIRED=True, MANUAL_TRADING_ENABLED=True,
    )

    class FakeDB:
        def get_account_state(self, account_id):
            return type("Account", (), {"balance": 10000.0, "initial_capital": 10000.0})()

        def get_daily_pnl(self, account_id, date):
            return type("Daily", (), {"pnl": 0.0})()

        def get_open_positions(self, account_id):
            return []

    class FakeReconciler:
        async def reconcile(self):
            return {"status": "ok"}

    class ReadyExecution(FakeExecution):
        def __init__(self):
            self.db_manager = FakeDB()
            self.account_id = "default_account"
            self.reconciler = FakeReconciler()

    class FakeRisk:
        def __init__(self, settings, db_manager):
            pass

        @staticmethod
        def quote_equivalent_balance(balances, symbol, price):
            return 10000.0

        @staticmethod
        def validate_order(order, balance, context):
            return {"valid": True, "quantity": float(order["quantity"]), "price": float(order["price"])}

    class ReadyConnector:
        is_connected = True

        @staticmethod
        def canonical_symbol(symbol):
            return "EUR/USD"

        async def get_account_balance(self):
            return {"USD": 10000.0, "EUR": 1000.0}

        async def place_order(self, *args, **kwargs):
            return {"status": "success"}

    monkeypatch.setattr("execution.order_manager.RiskAI", FakeRisk)
    connector = ReadyConnector()
    manager = OrderManager(settings, connector, ReadyExecution())
    pending = asyncio.run(manager.submit({"symbol": "EURUSD", "action": "buy", "quantity": 1000, "price": 1.08}))
    assert pending["status"] == "pending_confirmation"
    assert pending["order"]["symbol"] == "EUR/USD"
    result = asyncio.run(manager.confirm(pending["confirmation_token"], approved=True))
    assert result["execution"]["status"] == "success"
    assert manager.parse_command("comprar BTC 0.01", "crypto")["symbol"] == "BTC/USDT"


def test_live_order_is_blocked_without_explicit_enablement():
    settings = Settings(MARKET_ADAPTER="binance", BINANCE_MODE="demo", MANUAL_TRADING_ENABLED=False, AUTONOMOUS_TRADING_ENABLED=False)

    class FakeConnector:
        market = "crypto"

        def canonical_symbol(self, symbol):
            return "BTC/USDT"

    manager = OrderManager(settings, FakeConnector(), FakeExecution())
    result = asyncio.run(manager.submit({"symbol": "BTC/USDT", "action": "buy", "quantity": 0.01, "price": 100.0}, confirmed=True))
    assert result["status"] == "rejected"
    assert result["reason"] == "negociação manual desabilitada"


def test_adaptive_kelly_reduces_risk_when_volatility_is_high():
    low_volatility = [0.01] * 15 + [-0.005] * 5
    high_volatility = [0.10] * 15 + [-0.08] * 5
    sizer = AdaptiveKellySizer(fraction=0.25, target_volatility=0.02, max_risk_fraction=0.02)
    low = sizer.estimate(low_volatility, reward_risk=2.0)
    high = sizer.estimate(high_volatility, reward_risk=2.0)
    assert low["status"] == "ok"
    assert high["status"] == "ok"
    assert high["volatility_adjustment"] < low["volatility_adjustment"]
    assert high["risk_fraction"] <= low["risk_fraction"]
    assert high["risk_fraction"] <= 0.02


def test_premarket_gate_blocks_missing_news_context():
    settings = Settings(NEWS_FAIL_CLOSED_FOR_ENTRY=True, NEWS_MIN_HEALTHY_PROVIDERS=1, NEWS_MIN_ARTICLES_FOR_ENTRY=1)
    index = pd.date_range("2026-01-01", periods=50, freq="h", tz="UTC")
    close = np.linspace(100.0, 101.0, 50)
    frame = pd.DataFrame({"close": close}, index=index)
    result = PreMarketGate(settings).evaluate(frame, {"articles": [], "provider_health": {}})
    assert result["allowed"] is False
    assert result["status"] == "rejected"
