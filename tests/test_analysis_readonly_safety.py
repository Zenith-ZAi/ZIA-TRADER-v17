import asyncio
import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from config.settings import Settings
from core.command_manager import CoreCommandManager
from core.market_signals import calculate_market_signal
from core.regime_detector import MarketRegimeDetector



def closed_frame(size: int = 80, timeframe: str = "1h") -> pd.DataFrame:
    period = pd.Timedelta(timeframe)
    end = pd.Timestamp.now(tz="UTC") - (period * 2)
    index = pd.date_range(end=end, periods=size, freq=period)
    close = pd.Series(np.linspace(100.0, 140.0, size), index=index)
    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.3,
            "low": close - 0.3,
            "close": close,
            "volume": 1000.0,
        },
        index=index,
    )


class ReadOnlyMarket:
    def __init__(self, missing_timeframes: set[str] | None = None):
        self.missing_timeframes = missing_timeframes or set()
        self.history_requests: list[str] = []

    async def get_historical_data(self, symbol, timeframe, limit=250):
        self.history_requests.append(timeframe)
        frame = closed_frame(min(limit, 80), timeframe)
        assert frame.index[-1] < pd.Timestamp.now(tz="UTC")
        if timeframe in self.missing_timeframes:
            raise RuntimeError(f"histórico secundário indisponível: {timeframe}")
        return frame

    async def get_market_data(self, symbol):
        return {
            "symbol": symbol,
            "last": 140.0,
            "bid": 139.9,
            "ask": 140.1,
            "volume": 1000.0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "timestamp_source": "simulated",
        }

    async def get_order_book(self, symbol, limit=20):
        return {"symbol": symbol, "bids": [[139.9, 2.2]], "asks": [[140.1, 1.0]]}


class HealthyNews:
    async def fetch_all(self, tickers):
        return [
            {
                "title": "fresh market update",
                "sentiment_score": 0.1,
                "published_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
            }
        ]

    async def fetch_trending(self, tickers):
        return []

    @staticmethod
    def aggregate_sentiment(items):
        return sum(float(item.get("sentiment_score", 0.0)) for item in items) / len(items) if items else 0.0

    @staticmethod
    def aggregate_trend_score(items):
        return 0.0

    @staticmethod
    def health():
        return {"rss": {"enabled": True, "ok": True}}


def test_missing_required_secondary_history_never_authorizes_entry():
    market = ReadOnlyMarket(missing_timeframes={"5m"})
    settings = Settings(
        TIMEFRAME="1h",
        ANALYSIS_TIMEFRAMES="1h,5m",
        MULTI_TIMEFRAME_ENABLED=True,
        ORDER_FLOW_CONFIRMATION_REQUIRED=True,
        NEWS_FAIL_CLOSED_FOR_ENTRY=True,
        NEWS_MIN_HEALTHY_PROVIDERS=1,
        NEWS_MIN_ARTICLES_FOR_ENTRY=1,
    )
    manager = CoreCommandManager(settings, None, market, HealthyNews())

    result = asyncio.run(manager.analyze_symbol("BTC/USDT", limit=80))

    assert market.history_requests == ["1h", "5m"]
    assert result["signal"]["candidate_action"] == "buy"
    assert result["signal"]["action"] == "buy"
    assert result["signal"]["status"] == "good"
    assert result["data_sufficient"] is False
    assert result["status"] == "attention"
    assert result["entry_allowed"] is False
    assert result["execution_authorized"] is False
    assert result["orders_sent"] == 0
    assert "history:5m" in result["snapshot"]["errors"]
    assert any("histórico obrigatório" in reason for reason in result["explanation"])
    assert all("histórico secundário indisponível: 5m" not in reason for reason in result["explanation"])


def test_offline_news_can_never_open_the_news_entry_gate():
    market = ReadOnlyMarket()
    settings = Settings(
        TIMEFRAME="1h",
        ANALYSIS_TIMEFRAMES="1h",
        MULTI_TIMEFRAME_ENABLED=False,
        ORDER_FLOW_CONFIRMATION_REQUIRED=True,
        NEWS_FAIL_CLOSED_FOR_ENTRY=False,
        NEWS_MIN_HEALTHY_PROVIDERS=0,
        NEWS_MIN_ARTICLES_FOR_ENTRY=0,
    )
    manager = CoreCommandManager(settings, None, market, HealthyNews())

    result = asyncio.run(manager.analyze_symbol("BTC/USDT", offline=True, limit=80))

    assert result["news_gate"]["entry_allowed"] is False
    assert "offline" in result["news_gate"]["reason"]
    assert result["entry_allowed"] is False
    assert result["execution_authorized"] is False
    assert result["orders_sent"] == 0


@pytest.mark.parametrize("kind", ["nan", "inf", "missing", "inverted"])
def test_regime_invalid_ohlc_is_unknown_bad_data_with_finite_values(kind):
    frame = closed_frame(20).loc[:, ["high", "low", "close"]].copy()
    if kind == "nan":
        frame.iloc[-1, frame.columns.get_loc("close")] = np.nan
    elif kind == "inf":
        frame.iloc[-1, frame.columns.get_loc("high")] = np.inf
    elif kind == "missing":
        frame = frame.drop(columns=["low"])
    else:
        frame.iloc[-1, frame.columns.get_loc("high")] = frame.iloc[-1]["low"] - 1.0

    result = MarketRegimeDetector(lookback=20).detect(frame)

    assert result["regime"] == "unknown"
    assert result["status"] == "bad_data"
    for key in ("volatility_index", "trend_index", "action_multiplier"):
        assert math.isfinite(result[key])


def test_regime_valid_output_preserves_finite_classification():
    frame = closed_frame(20).loc[:, ["high", "low", "close"]]
    recent_range = frame["high"] - frame["low"]
    expected_volatility = float(recent_range.iloc[-1] / recent_range.mean())
    ema_short = frame["close"].ewm(span=10).mean()
    ema_long = frame["close"].ewm(span=20).mean()
    expected_trend = float((ema_short.iloc[-1] - ema_long.iloc[-1]) / ema_long.iloc[-1])

    result = MarketRegimeDetector(lookback=20).detect(frame)

    assert result["regime"] == "strong_trend"
    assert result["volatility_index"] == pytest.approx(expected_volatility)
    assert result["trend_index"] == pytest.approx(expected_trend)
    assert all(math.isfinite(result[key]) for key in ("volatility_index", "trend_index", "action_multiplier"))


def test_signal_prefixes_use_only_closed_data_and_remain_valid_after_35_bars():
    frame = closed_frame(64)
    results = [calculate_market_signal(frame.iloc[:end]) for end in range(35, len(frame) + 1)]

    assert len(results) == 30
    assert all(signal.status != "bad_data" for signal in results)
    assert all(math.isfinite(signal.score) and math.isfinite(signal.confidence) for signal in results)
    assert frame.index[-1] < pd.Timestamp.now(tz="UTC")
