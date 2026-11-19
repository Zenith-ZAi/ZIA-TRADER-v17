from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from database import MarketCandle
from database_manager import DatabaseManager


def candle(**overrides):
    value = {
        "source": "binance_public",
        "asset_class": "crypto",
        "symbol": "BTC/USDT",
        "timeframe": "1h",
        "timestamp": datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc),
        "open": 100.0,
        "high": 105.0,
        "low": 99.0,
        "close": 103.0,
        "volume": 10.0,
        "volume_status": "reported",
    }
    value.update(overrides)
    return value


def test_upsert_collapses_identical_duplicate_candle_keys(tmp_path):
    database = DatabaseManager(f"sqlite:///{tmp_path / 'candles.db'}")
    database.create_tables()
    try:
        rows = [candle(), candle()]
        assert database.upsert_market_candles(rows) == 1
        with database.SessionLocal() as session:
            assert session.scalar(select(func.count()).select_from(MarketCandle)) == 1
    finally:
        database.engine.dispose()


def test_upsert_rejects_conflicting_duplicate_candle_keys_before_persisting(tmp_path):
    database = DatabaseManager(f"sqlite:///{tmp_path / 'conflicting-candles.db'}")
    database.create_tables()
    try:
        with pytest.raises(ValueError, match="duplicate candle key has conflicting values"):
            database.upsert_market_candles([candle(), candle(close=104.0)])
        with database.SessionLocal() as session:
            assert session.scalar(select(func.count()).select_from(MarketCandle)) == 0
    finally:
        database.engine.dispose()
