from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.data_quality import CentralDataQuality, DataAvailability
from core.historical_backfill import HistoricalBackfill


def test_data_quality_fail_closed_and_complete_dataset():
    complete = CentralDataQuality.assess(
        source="binance_public", symbol="BTC/USDT", timeframe="1h",
        expected=24, received=24, persisted=24,
        provenance={"provider": "binance_public", "exchange_timestamp": "UTC"},
    )
    assert complete.state is DataAvailability.AVAILABLE
    partial = CentralDataQuality.assess(
        source="binance_public", symbol="BTC/USDT", timeframe="1h",
        expected=24, received=23, persisted=23, missing=1,
    )
    assert partial.state is DataAvailability.PARTIAL
    assert partial.completeness_percent == pytest.approx(95.8333)
    safe, reasons = CentralDataQuality.safe_for_inference([partial])
    assert safe is False
    assert reasons


def test_provider_unavailable_and_invalid_states():
    unavailable = CentralDataQuality.assess(
        source="alpha_vantage", symbol="EUR/USD", timeframe="1d",
        expected=5, received=0, persisted=0, provider_available=False,
    )
    invalid = CentralDataQuality.assess(
        source="binance_public", symbol="BTC/USDT", timeframe="1h",
        expected=5, received=5, persisted=5, invalid=1,
    )
    assert unavailable.state is DataAvailability.SOURCE_UNAVAILABLE
    assert invalid.state is DataAvailability.INVALID


def test_backfill_identifies_missing_windows_and_is_idempotent():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    existing = [start, start + timedelta(hours=1), start + timedelta(hours=3)]
    backfill = HistoricalBackfill(
        fetch_missing=None,
        upsert_candles=lambda rows: len(rows),
        interval_seconds=3600,
    )
    windows = backfill.missing_windows(existing, start, start + timedelta(hours=3), 3600)
    assert windows == [(start + timedelta(hours=2), start + timedelta(hours=2))]


def test_backfill_repeated_import_updates_valid_rows_via_upsert():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    import_counts = []

    async def fetch(_symbol, _timeframe, window_start, _window_end):
        return [{"timestamp": window_start, "close": 100.0}]

    def upsert(rows):
        import_counts.append(len(rows))
        return len(rows)

    backfill = HistoricalBackfill(fetch_missing=fetch, upsert_candles=upsert, interval_seconds=3600)

    import asyncio
    first = asyncio.run(backfill.run(symbol="BTC/USDT", timeframe="1h", existing=[], start=start, end=start))
    second = asyncio.run(backfill.run(symbol="BTC/USDT", timeframe="1h", existing=[start], start=start, end=start))
    assert first.persisted == 1
    assert second.status == "no_missing_intervals"
    assert import_counts == [1]
