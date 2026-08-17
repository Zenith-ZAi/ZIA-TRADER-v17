import asyncio
from datetime import datetime

import numpy as np
import pandas as pd

from config.settings import Settings
from core.backtest_engine import BacktestEngine
from core.market_signals import calculate_market_signal
from data.news_processor import NewsProcessor
from database import MarketType
from database_manager import DatabaseManager
from risk.risk_ai import RiskAI


def make_ohlcv(length: int = 320, shock: float = 0.0) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    returns = rng.normal(0.0008, 0.008, length)
    returns[120:180] += 0.0015
    close = 100 * np.exp(np.cumsum(returns))
    if shock:
        close[-1] = close[-2] * (1 + shock)
    open_price = np.r_[close[0], close[:-1]]
    high = np.maximum(open_price, close) * 1.004
    low = np.minimum(open_price, close) * 0.996
    volume = rng.lognormal(mean=8, sigma=0.25, size=length)
    index = pd.date_range("2025-01-01", periods=length, freq="h")
    return pd.DataFrame(
        {"open": open_price, "high": high, "low": low, "close": close, "volume": volume},
        index=index,
    )


def make_settings(**overrides):
    values = {
        "DATABASE_URL": "sqlite:///:memory:",
        "BACKTEST_MAX_VOLATILITY": 0.08,
        "MIN_CONFIDENCE_THRESHOLD": 0.70,
        "MAX_RISK_PER_TRADE": 0.02,
        "STOP_LOSS_PCT": 0.02,
        "TAKE_PROFIT_PCT": 0.05,
        "MAX_EXPOSURE_PER_SYMBOL": 0.10,
        "MAX_TOTAL_EXPOSURE": 0.30,
        "DAILY_LOSS_LIMIT_PERCENT": 0.05,
        "NEWS_CACHE_TTL_SECONDS": 300,
        "NEWS_MAX_ARTICLES": 20,
        "GDELT_BASE_URL": "https://test.local/gdelt",
        "COINGECKO_BASE_URL": "https://test.local/coingecko",
    }
    values.update(overrides)
    return Settings(**values)


def test_market_signal_rejects_extreme_volatility():
    signal = calculate_market_signal(make_ohlcv(shock=2.0), max_volatility=0.04)
    assert signal.action == "hold"
    assert signal.status == "rejected"
    assert any("volatilidade" in reason for reason in signal.reasons)


def test_backtest_is_deterministic_and_reports_risk_metrics():
    settings = make_settings()
    engine = BacktestEngine(settings, None)
    data = make_ohlcv()
    first = asyncio.run(engine.run("BTC/USDT", data, "IA Adaptativa"))
    second = asyncio.run(engine.run("BTC/USDT", data, "IA Adaptativa"))

    assert first["status"] == "ok"
    assert first["trades_executed"] == len(first["trades"])
    assert np.isfinite(first["total_pnl"])
    assert np.isfinite(first["sharpe_ratio"])
    assert first["max_drawdown"] <= 0
    assert first["signal_quality"] == second["signal_quality"]
    assert first["total_pnl"] == second["total_pnl"]


def test_risk_ai_limits_daily_loss_and_exposure(tmp_path):
    settings = make_settings(DATABASE_URL=f"sqlite:///{tmp_path / 'risk.db'}")
    db = DatabaseManager(settings.DATABASE_URL)
    db.create_tables()
    db.create_or_update_account_state("default_account", 10000.0, 10000.0)
    risk = RiskAI(settings, db)

    accepted = risk.validate_order(
        {"symbol": "BTC/USDT", "action": "buy", "price": 100.0, "confidence": 0.95},
        10000.0,
    )
    assert accepted["valid"] is True
    assert accepted["projected_notional"] <= 1000.0

    db.create_position("default_account", "BTC/USDT", MarketType.CRYPTO, 10.0, 100.0, 100.0)
    blocked_exposure = risk.validate_order(
        {"symbol": "BTC/USDT", "action": "buy", "price": 100.0, "confidence": 0.95},
        10000.0,
    )
    assert blocked_exposure["valid"] is False
    assert "símbolo" in blocked_exposure["reason"]

    db.create_or_update_daily_pnl("default_account", datetime.now(), -600.0, -0.06)
    blocked_loss = risk.validate_order(
        {"symbol": "ETH/USDT", "action": "buy", "price": 100.0, "confidence": 0.95},
        10000.0,
    )
    assert blocked_loss["valid"] is False
    assert "diária" in blocked_loss["reason"]


def test_news_processor_uses_free_sources_without_mock_news(monkeypatch):
    settings = make_settings()
    processor = NewsProcessor(settings)

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def fake_get(url, params, headers, timeout):
        if "gdelt" in url:
            return FakeResponse({"articles": [{"title": "Bitcoin bullish growth", "url": "https://example.test/a", "seendate": "20260817T120000Z"}]})
        return FakeResponse({"coins": [{"item": {"symbol": "BTC", "name": "Bitcoin", "market_cap_rank": 1, "data": {}}}]})

    monkeypatch.setattr("data.news_processor.requests.get", fake_get)
    articles = asyncio.run(processor.fetch_all(["BTC/USDT"]))
    trends = asyncio.run(processor.fetch_trending(["BTC/USDT"]))

    assert articles[0]["source"] == "GDELT"
    assert articles[0]["title"] == "Bitcoin bullish growth"
    assert trends[0]["provider"] == "CoinGecko"
    assert processor.health()["gdelt"]["ok"] is True


def test_optional_benzinga_trend_provider(monkeypatch):
    settings = make_settings(BENZINGA_API_KEY="test-token")
    processor = NewsProcessor(settings)

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def fake_get(url, params, headers, timeout):
        if "trending-tickers" in url:
            return FakeResponse({"data": [{"ticker": "BTC", "metrics": [{"scaled_count_mavg": 0.82, "count": 42}]}]})
        return FakeResponse({"coins": []})

    monkeypatch.setattr("data.news_processor.requests.get", fake_get)
    trends = asyncio.run(processor.fetch_trending(["BTC/USDT"]))
    paid = [trend for trend in trends if trend["provider"] == "Benzinga"]
    assert paid[0]["trend_score"] == 0.82
