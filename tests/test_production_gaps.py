from __future__ import annotations

import asyncio

import pandas as pd
import pytest

from config.settings import Settings
from core.feature_pipeline import FeaturePipeline
from core.reconciliation import OrderReconciler
from database_manager import DatabaseManager
from execution.mainnet_adapter import BinanceMainnetAdapter, MainnetDisabledError
from execution.oco_manager import OCOManager
from security.rate_limiter import RateLimiter


class FakeExchange:
    def __init__(self):
        self.calls = []
        self.fail_once = True

    async def send(self, order):
        self.calls.append(dict(order))
        if self.fail_once:
            self.fail_once = False
            raise TimeoutError("transporte indisponível")
        return {
            "status": "success",
            "order_id": "ex-1",
            "filled_price": 100.0,
            "filled_quantity": float(order["quantity"]),
        }

    async def get_open_orders(self):
        return [{"client_order_id": "zia_pending", "order_id": "ex-pending"}]

    async def get_positions(self):
        return [{"symbol": "BTC/USDT", "action": "buy", "quantity": 0.1}]


class FakeProtectionExchange:
    async def place_protection_order(self, protection):
        if protection["order_type"] == "take_profit_limit":
            return {"status": "error", "reason": "mock partial fill"}
        return {"status": "success", "order_id": "sl-1", "filled_quantity": 0.0}

    async def place_oco_orders(self, payload):
        return {"status": "unsupported"}

    async def cancel_order(self, order_id):
        return {"status": "success", "order_id": order_id}


def make_db(tmp_path):
    db = DatabaseManager(f"sqlite:///{tmp_path / 'gaps.db'}")
    db.create_tables()
    return db


def test_reconciler_retries_with_same_client_order_id_and_reuses_result(tmp_path):
    db = make_db(tmp_path)
    exchange = FakeExchange()
    reconciler = OrderReconciler(db, exchange, max_attempts=2, base_delay_seconds=0.0)

    async def run():
        first = await reconciler.submit_with_retry(
            {"symbol": "BTC/USDT", "action": "buy", "quantity": 0.1, "price": 100.0},
            exchange.send,
            client_order_id="zia_test_1",
        )
        second = await reconciler.submit_with_retry(
            {"symbol": "BTC/USDT", "action": "buy", "quantity": 0.1, "price": 100.0},
            exchange.send,
            client_order_id="zia_test_1",
        )
        return first, second

    first, second = asyncio.run(run())
    assert first["status"] == "success"
    assert second["status"] == "idempotent_reuse"
    assert len(exchange.calls) == 2
    assert {call["client_order_id"] for call in exchange.calls} == {"zia_test_1"}


def test_reconciler_sync_positions_reports_difference(tmp_path):
    db = make_db(tmp_path)
    db.upsert_runtime_position("default_account", {"symbol": "BTC/USDT", "action": "sell", "quantity": 0.1, "entry_price": 100.0})
    reconciler = OrderReconciler(db, FakeExchange())
    result = asyncio.run(reconciler.sync_positions())
    assert result["status"] == "attention"
    assert result["differences"][0]["symbol"] == "BTC/USDT"


def test_oco_manager_persists_partial_protection(tmp_path):
    db = make_db(tmp_path)
    manager = OCOManager(FakeProtectionExchange(), db)
    result = asyncio.run(manager.attach_protection(
        {"symbol": "BTC/USDT", "action": "buy", "quantity": 0.1, "client_order_id": "parent-1"},
        stop_loss=95.0,
        take_profit=110.0,
    ))
    assert result["status"] == "partial"
    assert len(result["protections"]) == 2
    assert len(db.list_active_protection_orders("default_account", "parent-1")) == 1


def test_mainnet_is_fail_closed_by_default():
    settings = Settings(
        BINANCE_MODE="live",
        BINANCE_API_KEY="key",
        BINANCE_SECRET_KEY="secret",
        LIVE_TRADING_ENABLED=False,
        LIVE_MODE=False,
        SHADOW_MODE_ENABLED=True,
    )
    with pytest.raises(MainnetDisabledError):
        BinanceMainnetAdapter(settings)


def test_rate_limiter_returns_429_decision_without_sleeping():
    limiter = RateLimiter(rate_limit=2, interval=60)
    assert limiter.allow("client") is True
    assert limiter.allow("client") is True
    assert limiter.allow("client") is False
    assert limiter.retry_after("client") >= 1


def test_feature_pipeline_has_same_causal_schema_for_live_and_backtest():
    index = pd.date_range("2026-01-01", periods=80, freq="h", tz="UTC")
    close = pd.Series(range(100, 180), index=index, dtype=float)
    frame = pd.DataFrame({
        "open": close - 0.5,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": 1000.0,
    }, index=index)
    pipeline = FeaturePipeline()
    live_features = pipeline.build_features(frame)
    backtest_features = pipeline.build_features(frame.copy())
    pd.testing.assert_frame_equal(live_features, backtest_features)
    assert pipeline.schema == list(live_features.columns)


def test_http_rate_limit_returns_429():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.middleware import RequestRateLimitMiddleware

    app = FastAPI()
    app.add_middleware(
        RequestRateLimitMiddleware,
        settings=Settings(API_RATE_LIMIT_BY_IP=2, API_RATE_LIMIT_BY_USER=10, API_RATE_LIMIT_INTERVAL=60),
    )

    @app.get("/test_rate_limit")
    async def _test_rate_limit():
        return {"status": "ok"}

    with TestClient(app) as client:
        assert client.get("/test_rate_limit").status_code == 200
        assert client.get("/test_rate_limit").status_code == 200
        response = client.get("/test_rate_limit")
        assert response.status_code == 429
        assert response.json()["detail"] == "rate_limit_exceeded"
