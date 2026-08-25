from datetime import datetime, timedelta, timezone

import pandas as pd

from config.settings import Settings
from core.daily_state_manager import DailyStateManager
from core.data_feeds import MultiTimeframeFeed
from core.flow_analysis import analyze_order_flow
from core.command_manager import CoreCommandManager
from core.learning_layer import SignalLearningLayer
from database_manager import DatabaseManager


def _frame(size=80):
    index = pd.date_range("2026-08-20", periods=size, freq="h", tz="UTC")
    close = pd.Series([100.0 + (index_position * 0.2) for index_position in range(size)], index=index)
    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.4,
            "low": close - 0.4,
            "close": close,
            "volume": 1000.0,
        },
        index=index,
    )


def test_order_flow_requires_complete_two_to_one_book():
    bullish = analyze_order_flow({"bids": [[100.0, 2.2]], "asks": [[101.0, 1.0]]})
    bearish = analyze_order_flow({"bids": [[100.0, 1.0]], "asks": [[101.0, 2.2]]})
    neutral = analyze_order_flow({"bids": [[100.0, 1.5]], "asks": [[101.0, 1.0]]})
    incomplete = analyze_order_flow({"bids": [[100.0, 5.0]], "asks": []})

    assert bullish["action"] == "buy"
    assert bearish["action"] == "sell"
    assert neutral["action"] == "hold"
    assert incomplete["action"] == "hold"
    assert incomplete["data_available"] is False


class _News:
    async def fetch_all(self, tickers):
        return [{"title": "market", "sentiment_score": 0.1}]

    async def fetch_trending(self, tickers):
        return [{"symbol": "BTC", "price_change_24h": 2.0, "trend_score": 1.0}]

    @staticmethod
    def aggregate_sentiment(items):
        return sum(item["sentiment_score"] for item in items) / len(items)


class _Market:
    async def get_historical_data(self, symbol, timeframe, limit=250):
        return _frame(min(limit, 80))

    async def get_market_data(self, symbol):
        return {"symbol": symbol, "last": 115.8, "bid": 115.7, "ask": 115.9, "volume": 1000.0}

    async def get_order_book(self, symbol, limit=20):
        return {"symbol": symbol, "bids": [[115.7, 2.2]], "asks": [[115.9, 1.0]]}


def test_multi_timeframe_feed_and_learning_layer(tmp_path):
    settings = Settings(
        DATABASE_URL=f"sqlite:///{tmp_path / 'learning.db'}",
        ANALYSIS_TIMEFRAMES="15m,1h",
        TIMEFRAME="1h",
        LEARNING_FORWARD_HORIZON_BARS=2,
    )
    db = DatabaseManager(settings.DATABASE_URL)
    db.create_tables()
    feed = MultiTimeframeFeed(_Market(), _News(), settings)
    snapshot = __import__("asyncio").run(feed.fetch_snapshot("BTC/USDT", limit=80))
    assert set(snapshot.historical) == {"15m", "1h"}
    assert snapshot.order_flow["action"] == "buy"
    assert snapshot.trends[0]["price_change_24h"] == 2.0

    observed_at = _frame().index[-4].to_pydatetime()
    db.create_ai_observation({
        "symbol": "BTC/USDT",
        "observed_at": observed_at.replace(tzinfo=None),
        "mode": "shadow",
        "action": "buy",
        "candidate_action": "buy",
        "confidence": 0.8,
        "price": 100.0,
        "metadata_json": {"before": {"flow": snapshot.order_flow}},
    })
    summary = SignalLearningLayer(db, settings).label_observations(_frame(), "BTC/USDT", horizon_bars=2)
    assert summary["observations_labeled"] == 1
    record = db.get_ai_observations("BTC/USDT", limit=1)[0]
    assert record.outcome_label == 1
    assert record.metadata_json["after"]["future_price"] > 100.0


def test_core_command_analyzes_without_orders(tmp_path):
    settings = Settings(
        DATABASE_URL=f"sqlite:///{tmp_path / 'command.db'}",
        TIMEFRAME="1h",
        ANALYSIS_TIMEFRAMES="1h",
        ORDER_FLOW_CONFIRMATION_REQUIRED=True,
    )
    db = DatabaseManager(settings.DATABASE_URL)
    db.create_tables()
    result = __import__("asyncio").run(
        CoreCommandManager(settings, db, _Market(), _News()).analyze_symbol("BTC/USDT", offline=True, limit=80)
    )
    assert result["orders_sent"] == 0
    assert result["snapshot"]["order_flow"]["action"] == "buy"
    assert "signal" in result and "indicators" in result["signal"]


def test_daily_state_blocks_neutral_and_two_losses():
    manager = DailyStateManager(max_wins=5, max_losses=2)
    now = datetime(2026, 8, 25, tzinfo=timezone.utc)
    assert manager.check_entry("hold", now)["allowed"] is False
    manager.record_trade(False, now)
    manager.record_trade(False, now)
    assert manager.check_entry("buy", now)["allowed"] is False
    tomorrow = now + timedelta(days=1)
    assert manager.check_entry("buy", tomorrow)["allowed"] is True
