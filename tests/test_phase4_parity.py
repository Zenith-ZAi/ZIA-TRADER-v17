from __future__ import annotations

import asyncio
import sys
import threading
import types
from dataclasses import asdict

import numpy as np
import pandas as pd
import pytest

from ai.feature_pipeline import build_feature_frame
from config.settings import Settings
from core.feature_pipeline import FeatureFrameCache
from core.market_signals import MarketSignalCache, calculate_market_signal
from core.pullback_registry import PullbackCacheRegistry
from core.pullback_strategy import PullbackSignalCache, calculate_pullback_signal
from execution.market_connector import ForexPublicReadOnlyAdapter, YahooB3Adapter
from infra.async_http import AsyncProviderHTTP


def ohlcv(rows: int = 180) -> pd.DataFrame:
    """Fixture de teste determinística; não representa dados de mercado observados."""
    rng = np.random.default_rng(20261007)
    index = pd.date_range("2024-01-01", periods=rows, freq="h", tz="UTC")
    returns = 0.0001 + 0.004 * rng.standard_normal(rows)
    close = 100.0 * np.cumprod(1.0 + returns)
    open_price = np.r_[close[0], close[:-1]]
    high = np.maximum(open_price, close) * (1.0 + rng.uniform(0.0001, 0.004, rows))
    low = np.minimum(open_price, close) * (1.0 - rng.uniform(0.0001, 0.004, rows))
    volume = rng.uniform(100.0, 1000.0, rows)
    return pd.DataFrame(
        {"open": open_price, "high": high, "low": low, "close": close, "volume": volume},
        index=index,
    )


def _assert_pullback_decision_equal(left, right) -> None:
    left_values = asdict(left)
    right_values = asdict(right)
    # The existing cache and canonical function use different explanatory wording;
    # all decision, risk-price and numeric indicator outputs must remain equivalent.
    left_values.pop("reasons")
    right_values.pop("reasons")
    assert left_values.keys() == right_values.keys()
    for key in left_values:
        if isinstance(left_values[key], float):
            assert left_values[key] == pytest.approx(right_values[key], rel=1e-12, abs=1e-12), key
        else:
            assert left_values[key] == right_values[key], key


def test_feature_cache_appends_incrementally_with_canonical_numeric_equivalence():
    data = ohlcv(180)
    cache = FeatureFrameCache()
    cache.get(data.iloc[:60])

    for end in (61, 80, 120, 180):
        actual = cache.get(data.iloc[:end])
        expected = build_feature_frame(data.iloc[:end])
        pd.testing.assert_frame_equal(actual, expected, check_exact=False, rtol=1e-12, atol=1e-12)
        assert cache._incremental_ready is True


def test_feature_cache_rebuilds_after_revision_or_sliding_window():
    data = ohlcv(100)
    cache = FeatureFrameCache()
    cache.get(data.iloc[:80])

    revised = data.iloc[:80].copy()
    revised.iloc[30, revised.columns.get_loc("close")] += 0.01
    actual_revised = cache.get(revised)
    expected_revised = build_feature_frame(revised)
    pd.testing.assert_frame_equal(actual_revised, expected_revised, check_exact=False, rtol=1e-12, atol=1e-12)

    slid = revised.iloc[1:].copy()
    actual_slid = cache.get(slid)
    expected_slid = build_feature_frame(slid)
    pd.testing.assert_frame_equal(actual_slid, expected_slid, check_exact=False, rtol=1e-12, atol=1e-12)


def test_pullback_cache_matches_canonical_calculation_at_each_prefix():
    data = ohlcv(140)
    cache = PullbackSignalCache(data, ema_period=50)

    # Include the first prefix accepted by the canonical length guard.
    for position in range(51, len(data)):
        expected = calculate_pullback_signal(data.iloc[:position + 1], ema_period=50)
        actual = cache.at(position)
        _assert_pullback_decision_equal(actual, expected)


def test_pullback_cache_matches_canonical_at_warmup_boundary():
    data = ohlcv(140)
    cache = PullbackSignalCache(data, ema_period=50)
    live = calculate_pullback_signal(data.iloc[:52], ema_period=50)
    cached = cache.at(51)

    # Candidate fields now match the canonical calculation at the first valid
    # prefix; the final action remains hold because no trigger is confirmed.
    _assert_pullback_decision_equal(cached, live)
    assert live.action == cached.action == "hold"
    assert live.candidate_action == cached.candidate_action == "buy"


def test_pullback_registry_incremental_append_matches_full_rebuild():
    data = ohlcv(100)
    registry = PullbackCacheRegistry()
    first = registry.get("BTC/USDT", "1h", data.iloc[:80], ema_period=50)
    appended = registry.get("BTC/USDT", "1h", data, ema_period=50)
    rebuilt = PullbackSignalCache(data, ema_period=50)

    assert appended is first
    assert len(appended.frame) == len(data)
    for position in range(80, len(data)):
        _assert_pullback_decision_equal(appended.at(position), rebuilt.at(position))


def test_live_calculator_and_backtest_cache_have_same_candle_only_decisions():
    data = ohlcv(150)
    backtest_cache = MarketSignalCache(data)

    for position in range(34, len(data)):
        live = calculate_market_signal(
            data.iloc[:position + 1],
            min_confidence=0.60,
            max_volatility=1.0,
        )
        backtest = backtest_cache.at(
            position,
            min_confidence=0.60,
            max_volatility=1.0,
        )
        assert live.action == backtest.action
        assert live.candidate_action == backtest.candidate_action
        assert live.status == backtest.status
        assert live.regime == backtest.regime
        assert live.confidence == pytest.approx(backtest.confidence, rel=1e-12, abs=1e-12)
        assert live.score == pytest.approx(backtest.score, rel=1e-12, abs=1e-12)
        assert live.volatility == pytest.approx(backtest.volatility, rel=1e-12, abs=1e-12)


def test_forex_legacy_provider_runs_in_worker_thread(monkeypatch):
    worker_threads: list[int] = []

    class FakeCurrencyRates:
        def get_rate(self, base, quote):
            worker_threads.append(threading.get_ident())
            return 1.2345

    package = types.ModuleType("forex_python")
    converter = types.ModuleType("forex_python.converter")
    converter.CurrencyRates = FakeCurrencyRates
    package.converter = converter
    monkeypatch.setitem(sys.modules, "forex_python", package)
    monkeypatch.setitem(sys.modules, "forex_python.converter", converter)

    transport = AsyncProviderHTTP(client=object(), max_retries=0)
    adapter = ForexPublicReadOnlyAdapter(Settings(), http_client=transport)
    event_loop_thread = threading.get_ident()
    result = asyncio.run(adapter.get_market_data("EUR/USD"))

    assert result["last"] == 1.2345
    assert result["source"] == "forex-python"
    assert worker_threads and worker_threads[0] != event_loop_thread


def test_owned_read_only_adapter_transport_can_reconnect_after_close():
    async def run():
        for adapter in (YahooB3Adapter(Settings()), ForexPublicReadOnlyAdapter(Settings())):
            await adapter.connect()
            original = adapter.http_client
            await adapter.close()
            assert original.client.is_closed
            await adapter.connect()
            assert adapter.http_client is not original
            assert not adapter.http_client.client.is_closed
            await adapter.close()

    asyncio.run(run())
