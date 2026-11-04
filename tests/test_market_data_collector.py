from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select, func

from database import MarketCandle
from database_manager import DatabaseManager
from core.market_data_collector import (
    MarketDataCollectionError,
    ProviderCollectionError,
    UnifiedMarketDataCollector,
    canonical_symbol,
)


class StubHTTP:
    def __init__(self, payload: Any):
        self.payload = payload
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def get_json(self, provider: str, url: str, *, params: dict[str, Any]) -> Any:
        self.calls.append((provider, url, params))
        return self.payload


class StubDatabase:
    def __init__(self):
        self.rows: list[dict[str, Any]] = []

    def upsert_market_candles(self, candles: list[dict[str, Any]]) -> int:
        self.rows.extend(candles)
        return len(candles)


def make_settings(**overrides: Any) -> SimpleNamespace:
    values = {
        "MARKET_DATA_INGESTION_ENABLED": True,
        "MARKET_DATA_BINANCE_PUBLIC_ENABLED": True,
        "MARKET_DATA_ALPHA_VANTAGE_ENABLED": False,
        "ALPHA_VANTAGE_API_KEY": None,
        "BINANCE_PUBLIC_BASE_URL": "https://data-api.binance.vision",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def closed_binance_row() -> list[Any]:
    # A fully closed daily candle; timestamps are deterministic and independent of wall time.
    opened = datetime(2020, 1, 1, tzinfo=timezone.utc)
    closed = datetime(2020, 1, 1, 23, 59, 59, tzinfo=timezone.utc)
    return [int(opened.timestamp() * 1000), "100", "110", "90", "105", "42", int(closed.timestamp() * 1000)]


def test_canonical_symbols_retain_asset_identity() -> None:
    assert canonical_symbol("crypto", " btc-usdt ") == "BTC/USDT"
    assert canonical_symbol("forex", "eurusd") == "EUR/USD"
    assert canonical_symbol("equity", "brk.b") == "BRK.B"
    with pytest.raises(MarketDataCollectionError, match="crypto_quote_currency_required"):
        canonical_symbol("crypto", "BTC")


def test_dry_run_normalizes_candles_without_persisting_or_touching_trade_feed() -> None:
    http = StubHTTP([closed_binance_row()])
    db = StubDatabase()
    collector = UnifiedMarketDataCollector(make_settings(), db, http=http)

    result = asyncio.run(
        collector.collect(
            asset_class="crypto",
            symbols=["btcusdt"],
            providers=["binance_public"],
            timeframe="1d",
            limit=10,
            dry_run=True,
        )
    )

    assert result["status"] == "completed"
    assert result["mode"] == "dry_run"
    assert result["provider_results"][0]["status"] == "preview"
    assert result["requested_symbols"] == ["BTC/USDT"]
    assert result["orders_sent"] == 0
    assert result["trading_feed_updated"] is False
    assert result["model_weights_changed"] is False
    assert db.rows == []
    assert http.calls[0][2] == {"symbol": "BTCUSDT", "interval": "1d", "limit": 10}


def test_persisted_collection_writes_provider_and_asset_identity() -> None:
    collector = UnifiedMarketDataCollector(
        make_settings(), StubDatabase(), http=StubHTTP([closed_binance_row()])
    )

    result = asyncio.run(
        collector.collect(
            asset_class="crypto",
            symbols=["BTC/USDT"],
            providers=["binance_public"],
            timeframe="1d",
            limit=10,
            dry_run=False,
        )
    )

    assert result["provider_results"][0]["status"] == "persisted"
    assert result["provider_results"][0]["persisted_rows"] == 1
    row = collector.db_manager.rows[0]
    assert row["source"] == "binance_public"
    assert row["asset_class"] == "crypto"
    assert row["symbol"] == "BTC/USDT"
    assert row["timeframe"] == "1d"


def test_market_candle_upsert_is_idempotent_and_keeps_providers_separate(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "test")
    database = DatabaseManager(f"sqlite:///{tmp_path / 'market-candles.sqlite'}")
    try:
        database.create_tables()
        timestamp = datetime(2020, 1, 1, tzinfo=timezone.utc)
        binance = {
            "source": "binance_public",
            "asset_class": "crypto",
            "symbol": "BTC/USDT",
            "timeframe": "1d",
            "timestamp": timestamp,
            "open": 100.0,
            "high": 110.0,
            "low": 90.0,
            "close": 105.0,
            "volume": 42.0,
            "volume_status": "reported",
        }
        assert database.upsert_market_candles([binance]) == 1
        corrected = {**binance, "close": 106.0}
        assert database.upsert_market_candles([corrected]) == 1
        assert database.upsert_market_candles([{**binance, "source": "alpha_vantage", "close": 104.0}]) == 1

        with database.SessionLocal() as session:
            count = session.scalar(select(func.count()).select_from(MarketCandle))
            rows = session.scalars(select(MarketCandle).order_by(MarketCandle.source)).all()
        assert count == 2
        assert [(row.source, row.close) for row in rows] == [
            ("alpha_vantage", 104.0),
            ("binance_public", 106.0),
        ]
    finally:
        database.engine.dispose()


def test_yahoo_and_coingecko_are_reported_as_blocked_without_network_calls() -> None:
    http = StubHTTP([])
    collector = UnifiedMarketDataCollector(make_settings(), StubDatabase(), http=http)

    result = asyncio.run(
        collector.collect(
            asset_class="crypto",
            symbols=["BTC/USDT"],
            providers=["yahoo_chart", "coingecko"],
            timeframe="1d",
            dry_run=True,
        )
    )

    assert [row["status"] for row in result["provider_results"]] == ["blocked", "blocked"]
    assert [row["error_code"] for row in result["provider_results"]] == [
        "source_not_approved_for_automated_ingestion",
        "dataset_semantics_not_ohlcv",
    ]
    assert http.calls == []


def test_global_ingestion_gate_fails_closed() -> None:
    collector = UnifiedMarketDataCollector(
        make_settings(MARKET_DATA_INGESTION_ENABLED=False), StubDatabase(), http=StubHTTP([])
    )

    with pytest.raises(ProviderCollectionError, match="ingestion_disabled"):
        asyncio.run(
            collector.collect(
                asset_class="crypto",
                symbols=["BTC/USDT"],
                providers=["binance_public"],
                dry_run=True,
            )
        )


def test_provider_request_cancellation_propagates_to_caller() -> None:
    class CancelledHTTP:
        async def get_json(self, *_args: Any, **_kwargs: Any) -> Any:
            raise asyncio.CancelledError()

    collector = UnifiedMarketDataCollector(make_settings(), StubDatabase(), http=CancelledHTTP())
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            collector.collect(
                asset_class="crypto",
                symbols=["BTC/USDT"],
                providers=["binance_public"],
                timeframe="1d",
                dry_run=True,
            )
        )


def test_provider_endpoint_allowlist_rejects_redirect_or_untrusted_host_configuration() -> None:
    with pytest.raises(ProviderCollectionError, match="provider_endpoint_not_allowlisted"):
        UnifiedMarketDataCollector._validate_base_url(
            "https://attacker.example/api", "data-api.binance.vision"
        )
    with pytest.raises(ProviderCollectionError, match="provider_endpoint_not_allowlisted"):
        UnifiedMarketDataCollector._validate_base_url(
            "http://data-api.binance.vision", "data-api.binance.vision"
        )
