from __future__ import annotations

import asyncio

import pandas as pd
import pytest

from config.settings import Settings
from core.data_feeds import FeedUnavailable, MultiTimeframeFeed
from core.feed_quality import FeedQualityError, assess_ohlcv_quality


def make_frame(index: pd.DatetimeIndex) -> pd.DataFrame:
    close = pd.Series([100.0 + i for i in range(len(index))], index=index, dtype=float)
    return pd.DataFrame({
        "open": close,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": 10.0,
    }, index=index)


def test_crypto_gap_and_stale_feed_are_rejected():
    now = pd.Timestamp("2026-01-05T12:05:00Z")
    index = pd.date_range(end=now.floor("h"), periods=8, freq="h")
    gapped = make_frame(index.delete(4))

    with pytest.raises(FeedQualityError, match="missing_candle") as gap_error:
        assess_ohlcv_quality(gapped, timeframe="1h", market="crypto", now=now)
    assert gap_error.value.incidents[0]["kind"] == "missing_candle"

    stale = make_frame(pd.date_range(end=now - pd.Timedelta(hours=5), periods=8, freq="h"))
    with pytest.raises(FeedQualityError, match="stale_feed") as stale_error:
        assess_ohlcv_quality(stale, timeframe="1h", market="crypto", now=now)
    assert stale_error.value.incidents[0]["kind"] == "stale_feed"


def test_duplicate_out_of_order_and_invalid_ohlcv_are_rejected():
    now = pd.Timestamp("2026-01-05T12:05:00Z")
    index = pd.date_range(end=now.floor("h"), periods=5, freq="h")
    frame = make_frame(index)

    duplicated = pd.concat([frame, frame.iloc[[-1]]])
    with pytest.raises(FeedQualityError, match="duplicados"):
        assess_ohlcv_quality(duplicated, timeframe="1h", now=now)

    out_of_order = frame.iloc[[0, 2, 1, 3, 4]]
    with pytest.raises(FeedQualityError, match="ordem"):
        assess_ohlcv_quality(out_of_order, timeframe="1h", now=now)

    invalid = frame.copy()
    invalid.loc[index[-1], "high"] = invalid.loc[index[-1], "close"] - 1
    with pytest.raises(FeedQualityError, match="high/low"):
        assess_ohlcv_quality(invalid, timeframe="1h", now=now)


def test_timestamp_column_is_normalized_and_future_timestamp_is_rejected():
    now = pd.Timestamp("2026-01-05T12:05:00Z")
    index = pd.date_range(end=now.floor("h"), periods=4, freq="h")
    frame = make_frame(index).reset_index(names="timestamp")
    report = assess_ohlcv_quality(frame, timeframe="1h", now=now)
    assert report["valid"] is True

    future_index = pd.date_range(end=now + pd.Timedelta(hours=2), periods=4, freq="h")
    with pytest.raises(FeedQualityError, match="future_timestamp"):
        assess_ohlcv_quality(make_frame(future_index), timeframe="1h", now=now)


def test_session_closures_do_not_become_false_b3_or_forex_gaps():
    now = pd.Timestamp("2026-01-06T13:05:00Z")
    b3_index = pd.DatetimeIndex(["2026-01-05T13:00:00Z", "2026-01-06T13:00:00Z"])
    b3 = assess_ohlcv_quality(make_frame(b3_index), timeframe="1h", market="b3", now=now)
    assert b3["valid"] is True
    assert b3["missing_candles"] == 0

    forex_index = pd.DatetimeIndex(["2026-01-02T20:00:00Z", "2026-01-04T22:00:00Z"])
    forex = assess_ohlcv_quality(
        make_frame(forex_index),
        timeframe="1h",
        market="forex",
        now=pd.Timestamp("2026-01-04T22:05:00Z"),
    )
    assert forex["valid"] is True
    assert forex["missing_candles"] == 0


def test_intraday_gap_within_b3_session_is_reported():
    now = pd.Timestamp("2026-01-05T16:05:00Z")
    # 13:00/14:00/16:00 UTC correspondem a barras no mesmo pregão B3.
    index = pd.DatetimeIndex(["2026-01-05T13:00:00Z", "2026-01-05T14:00:00Z", "2026-01-05T16:00:00Z"])
    with pytest.raises(FeedQualityError, match="missing_candle"):
        assess_ohlcv_quality(make_frame(index), timeframe="1h", market="b3", now=now)


class _InvalidMarket:
    market = "crypto"

    def __init__(self, frame):
        self.frame = frame
        self.quote_calls = 0

    async def get_historical_data(self, symbol, timeframe, limit=250):
        return self.frame

    async def get_market_data(self, symbol):
        self.quote_calls += 1
        return {"last": 100.0}

    async def get_order_book(self, symbol, limit=20):
        return {"bids": [], "asks": []}


class _News:
    async def fetch_all(self, symbols):
        return []

    async def fetch_trending(self, symbols):
        return []


def test_feed_quality_failure_uses_existing_gate_before_quote_or_signal():
    now = pd.Timestamp.now(tz="UTC").floor("h")
    index = pd.date_range(end=now, periods=8, freq="h").delete(4)
    market = _InvalidMarket(make_frame(index))
    settings = Settings(TIMEFRAME="1h", ANALYSIS_TIMEFRAMES="1h", MARKET_ADAPTER="binance")
    feed = MultiTimeframeFeed(market, _News(), settings)

    with pytest.raises(FeedUnavailable, match="missing_candle"):
        asyncio.run(feed.fetch_snapshot("BTC/USDT", limit=80))
    assert market.quote_calls == 0
