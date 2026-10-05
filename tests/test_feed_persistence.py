from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pandas as pd

from config.settings import Settings
from core.data_feeds import MultiTimeframeFeed
from database_manager import DatabaseManager


def make_frame() -> pd.DataFrame:
    now = pd.Timestamp.now(tz="UTC").floor("h")
    index = pd.date_range(end=now, periods=8, freq="h")
    close = pd.Series([100.0 + i for i in range(len(index))], index=index)
    return pd.DataFrame({
        "open": close,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": 10.0,
    }, index=index)


def test_data_gap_incidents_are_deduplicated_and_resolved(tmp_path):
    manager = DatabaseManager(f"sqlite:///{tmp_path / 'feed-gaps.db'}")
    manager.create_tables()
    incident = {
        "kind": "stale_feed",
        "gap_start": "2026-01-01T11:00:00+00:00",
        "gap_end": "2026-01-01T12:00:00+00:00",
        "details": {"age_seconds": 3600},
    }

    manager.record_feed_incidents("binance", "BTC/USDT", "1h", [incident])
    manager.record_feed_incidents("binance", "BTC/USDT", "1h", [incident])
    open_rows = manager.list_data_gaps("BTC/USDT", "open")
    assert len(open_rows) == 1
    assert open_rows[0]["details"]["kind"] == "stale_feed"

    manager.record_feed_incidents("binance", "BTC/USDT", "1h", [])
    assert manager.list_data_gaps("BTC/USDT", "open") == []
    assert manager.list_data_gaps("BTC/USDT", "resolved")[0]["status"] == "resolved"


def test_order_book_history_is_throttled_and_pruned_by_retention(tmp_path):
    manager = DatabaseManager(f"sqlite:///{tmp_path / 'book-history.db'}")
    manager.create_tables()
    now = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)
    book = {
        "bids": [{"price": 100.0, "quantity": 1.0}],
        "asks": [{"price": 101.0, "quantity": 2.0}],
        "last_update_id": 123,
    }

    manager.persist_order_book_snapshot(
        "binance", "BTC/USDT", book,
        observed_at=now - timedelta(days=10), retention_days=7, min_interval_seconds=60,
    )
    first_id = manager.persist_order_book_snapshot(
        "binance", "BTC/USDT", book,
        observed_at=now, retention_days=7, min_interval_seconds=60,
    )
    assert first_id is not None
    assert manager.persist_order_book_snapshot(
        "binance", "BTC/USDT", book,
        observed_at=now + timedelta(seconds=30), retention_days=7, min_interval_seconds=60,
    ) is None
    second_id = manager.persist_order_book_snapshot(
        "binance", "BTC/USDT", book,
        observed_at=now + timedelta(seconds=61), retention_days=7, min_interval_seconds=60,
    )
    assert second_id is not None

    rows = manager.list_order_book_snapshots("BTC/USDT")
    assert len(rows) == 2
    assert rows[0]["last_update_id"] == "123"
    assert rows[0]["bids"] == book["bids"]


class _Market:
    market = "crypto"

    def __init__(self):
        self.quote_calls = 0

    async def get_historical_data(self, symbol, timeframe, limit=250):
        return make_frame()

    async def get_market_data(self, symbol):
        self.quote_calls += 1
        return {"symbol": symbol, "last": 100.0, "bid": 99.9, "ask": 100.1}

    async def get_order_book(self, symbol, limit=20):
        return {
            "symbol": symbol,
            "bids": [[99.9, 2.0]],
            "asks": [[100.1, 1.5]],
            "last_update_id": 456,
        }


class _News:
    def __init__(self, manager):
        self.db_manager = manager

    async def fetch_all(self, symbols):
        return []

    async def fetch_trending(self, symbols):
        return []


def test_feed_persists_only_supported_real_depth(tmp_path):
    manager = DatabaseManager(f"sqlite:///{tmp_path / 'feed-book.db'}")
    manager.create_tables()
    settings = Settings(
        TIMEFRAME="1h",
        ANALYSIS_TIMEFRAMES="1h",
        MARKET_ADAPTER="binance",
        BINANCE_MODE="testnet",
        ORDER_BOOK_HISTORY_ENABLED=True,
        ORDER_BOOK_HISTORY_RETENTION_DAYS=7,
        ORDER_BOOK_HISTORY_INTERVAL_SECONDS=60,
    )
    feed = MultiTimeframeFeed(_Market(), _News(manager), settings)

    snapshot = asyncio.run(feed.fetch_snapshot("BTC/USDT", limit=80))
    assert snapshot.data_quality["1h"]["valid"] is True
    rows = manager.list_order_book_snapshots("BTC/USDT")
    assert len(rows) == 1
    assert rows[0]["last_update_id"] == "456"


def test_forex_unknown_volume_is_explicit_zero_and_reported(tmp_path):
    manager = DatabaseManager(f"sqlite:///{tmp_path / 'forex-volume.db'}")
    manager.create_tables()
    settings = Settings(TIMEFRAME="1h", ANALYSIS_TIMEFRAMES="1h", MARKET_ADAPTER="forex", FOREX_MODE="public")
    market = _Market()
    market.market = "forex"
    original_get_history = market.get_historical_data

    async def history_without_volume(symbol, timeframe, limit=250):
        frame = await original_get_history(symbol, timeframe, limit)
        frame["volume"] = None
        return frame

    market.get_historical_data = history_without_volume
    feed = MultiTimeframeFeed(market, _News(manager), settings)

    snapshot = asyncio.run(feed.fetch_snapshot("EUR/USD", limit=80))
    assert snapshot.data_quality["1h"]["volume_missing_rows_filled_zero"] == len(snapshot.primary_history)
    assert (snapshot.primary_history["volume"] == 0.0).all()


class _GappedMarket(_Market):
    async def get_historical_data(self, symbol, timeframe, limit=250):
        return make_frame().iloc[[0, 1, 2, 4, 5, 6, 7]]


def test_invalid_primary_feed_persists_gap_and_does_not_fetch_quote(tmp_path):
    from core.data_feeds import FeedUnavailable
    import pytest

    manager = DatabaseManager(f"sqlite:///{tmp_path / 'feed-block.db'}")
    manager.create_tables()
    settings = Settings(TIMEFRAME="1h", ANALYSIS_TIMEFRAMES="1h", MARKET_ADAPTER="binance")
    market = _GappedMarket()
    feed = MultiTimeframeFeed(market, _News(manager), settings)

    try:
        asyncio.run(feed.fetch_snapshot("BTC/USDT", limit=80))
    except FeedUnavailable as exc:
        assert "missing_candle" in str(exc)
    else:
        raise AssertionError("feed inválido deveria permanecer fechado")

    rows = manager.list_data_gaps("BTC/USDT", "open")
    assert any(row["details"]["kind"] == "missing_candle" for row in rows)
    assert market.quote_calls == 0
