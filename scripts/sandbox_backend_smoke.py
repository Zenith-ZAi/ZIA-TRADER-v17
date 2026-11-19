"""Isolated Binance public-data → SQLite → feature smoke; no execution adapters."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx
import numpy as np
import pandas as pd

from ai.feature_pipeline import build_feature_frame
from core.feature_pipeline import FeatureFrameCache
from core.market_data_collector import UnifiedMarketDataCollector, canonical_symbol
from core.market_signals import calculate_market_signal
from database import MarketCandle
from database_manager import DatabaseManager
from infra.async_http import AsyncProviderHTTP

MAX_LIMIT = 500
DB_FILENAME = "sandbox_backend_smoke.sqlite"
ARTIFACT_FILENAME = "sandbox_backend_smoke.json"


@dataclass(frozen=True)
class PublicDataSettings:
    """Only collector fields, fixed at construction; cannot contain account credentials.

    This deliberately does not import the application Settings singleton, load .env,
    evaluate config source code or modify os.environ. No execution object is created.
    """
    MARKET_DATA_INGESTION_ENABLED: bool = True
    MARKET_DATA_BINANCE_PUBLIC_ENABLED: bool = True
    MARKET_DATA_ALPHA_VANTAGE_ENABLED: bool = False
    BINANCE_PUBLIC_BASE_URL: str = "https://data-api.binance.vision"


class SmokeConfigurationError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _prepare_output(output_dir: str | Path | None):
    temporary = tempfile.TemporaryDirectory(prefix="zia-public-smoke-") if output_dir is None else None
    path = Path(temporary.name) if temporary else Path(output_dir).expanduser()
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise SmokeConfigurationError("output_dir_invalid")
    path.mkdir(parents=True, exist_ok=True)
    if any(path.iterdir()):
        raise SmokeConfigurationError("output_dir_not_empty")
    return path, temporary


def _query(database: DatabaseManager, symbol: str, timeframe: str):
    with database.SessionLocal() as session:
        rows = session.query(MarketCandle).filter(
            MarketCandle.source == "binance_public", MarketCandle.asset_class == "crypto",
            MarketCandle.symbol == symbol, MarketCandle.timeframe == timeframe,
        ).order_by(MarketCandle.timestamp).limit(MAX_LIMIT).all()
        return [{key: getattr(row, key) for key in (
            "source", "asset_class", "symbol", "timeframe", "timestamp",
            "open", "high", "low", "close", "volume", "volume_status",
        )} for row in rows]


def _features(rows):
    frame = pd.DataFrame(rows).set_index("timestamp")[["open", "high", "low", "close", "volume"]]
    cached = FeatureFrameCache().get(frame)
    canonical = build_feature_frame(frame)
    digest = hashlib.sha256(pd.util.hash_pandas_object(cached, index=True).to_numpy(dtype="uint64").tobytes()).hexdigest()
    finite = np.isfinite(cached.to_numpy(dtype=float)).all(axis=1)
    matched = cached.equals(canonical)
    return {"rows": len(cached), "columns": len(cached.columns), "valid_rows": int(finite.sum()),
            "valid": bool(finite.any() and matched), "canonical_match": matched, "sha256": digest}


def _analysis(rows):
    frame = pd.DataFrame(rows).set_index("timestamp")[["open", "high", "low", "close", "volume"]]
    signal = calculate_market_signal(frame)
    return {"action": signal.action, "candidate_action": signal.candidate_action,
            "confidence": signal.confidence, "status": signal.status, "regime": signal.regime,
            "reasons": signal.reasons, "execution_authorized": False}


def _base_result(symbol, timeframe, limit):
    return {
        "schema_version": "sandbox_backend_smoke_v1", "status": "attention",
        "request": {"source": "binance_public", "asset_class": "crypto", "symbol": symbol,
                    "timeframe": timeframe, "limit": limit},
        "rows": {"received": 0, "persisted": 0, "stored_before_reimport": 0,
                 "reimported": 0, "stored_after_reimport": 0},
        "features": {"valid": False}, "idempotency": {"count_unchanged": False, "http_calls": 0},
        "decision": {"action": "HOLD", "reasons": ["smoke_only_no_trade_intent", "risk_ledger_news_license_not_verified"]},
        "news": {"status": "not_requested"}, "orders_sent": 0,
        "checks": {"execution_adapters_imported": False},
    }


async def run_sandbox_backend_smoke(*, symbol="BTC/USDT", timeframe="1h", limit=100,
                                    output_dir: str | Path | None = None, http: Any | None = None):
    """Run only public read-only GETs. A mock transport may be injected by tests.

    Persistent output requires an empty directory; no existing database is reused.
    Cancelling a worker does not undo a DB commit already in progress. No order intent
    is created, and the DB is disposable audit data, not a financial source of truth.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise SmokeConfigurationError("limit_out_of_range")
    if canonical_symbol("crypto", symbol) != "BTC/USDT" or timeframe != "1h":
        raise SmokeConfigurationError("invalid_request")
    symbol = "BTC/USDT"
    path, temporary = _prepare_output(output_dir)
    db = None
    client = None
    transport = http
    attempts = 0
    result = _base_result(symbol, timeframe, limit)

    async def count_request(_request):
        nonlocal attempts
        attempts += 1

    try:
        db = DatabaseManager(f"sqlite:///{path / DB_FILENAME}")
        await asyncio.to_thread(db.create_tables)
        if transport is None:
            client = httpx.AsyncClient(timeout=httpx.Timeout(12, connect=4), follow_redirects=False,
                                       trust_env=False, event_hooks={"request": [count_request]})
            transport = AsyncProviderHTTP(client=client, max_retries=1)
        collector = UnifiedMarketDataCollector(PublicDataSettings(), db, http=transport)
        collected = await collector.collect(asset_class="crypto", symbols=[symbol], providers=["binance_public"],
                                            timeframe=timeframe, limit=limit, dry_run=False)
        source = collected["provider_results"][0]
        result["source"] = source
        if source["status"] != "persisted":
            result["error_code"] = source.get("error_code", "source_failure")
        else:
            rows = await asyncio.to_thread(_query, db, symbol, timeframe)
            before = len(rows)
            reimported = await asyncio.to_thread(db.upsert_market_candles, rows)
            after_rows = await asyncio.to_thread(_query, db, symbol, timeframe)
            after = len(after_rows)
            features = await asyncio.to_thread(_features, after_rows)
            result["analysis"] = await asyncio.to_thread(_analysis, after_rows)
            matches = before == after == reimported == source["rows_received"] == source["persisted_rows"]
            result["rows"] = {"received": source["rows_received"], "persisted": source["persisted_rows"],
                              "stored_before_reimport": before, "reimported": reimported, "stored_after_reimport": after}
            result["features"] = features
            result["idempotency"]["count_unchanged"] = before == after
            result["checks"].update({"closed_candles_persisted": matches, "idempotent_reimport": matches,
                                     "feature_frame_valid": features["valid"]})
            if matches and features["valid"]:
                result["status"] = "ok"
            else:
                result["error_code"] = "data_or_feature_validation_failed"
    except asyncio.CancelledError:
        raise
    except Exception:
        # Never stringify an upstream/DB exception or put request credentials in JSON.
        result["error_code"] = "smoke_internal_failure"
    finally:
        result["idempotency"]["http_calls"] = attempts if http is None else len(getattr(http, "calls", []))

        async def cleanup():
            try:
                if transport is not None:
                    await transport.aclose()
            finally:
                try:
                    if client is not None:
                        await client.aclose()
                finally:
                    if db is not None:
                        await asyncio.to_thread(db.engine.dispose)
                    if temporary is not None:
                        temporary.cleanup()

        task = asyncio.create_task(cleanup())
        cancelled = None
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError as exc:
                cancelled = exc
        await task
        if cancelled:
            raise cancelled
    if temporary is None:
        (path / ARTIFACT_FILENAME).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


run_smoke = run_sandbox_backend_smoke


def main():
    parser = argparse.ArgumentParser(description="Smoke read-only BTC/USDT 1h, sem chaves nem ordens")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()
    try:
        result = asyncio.run(run_sandbox_backend_smoke(limit=args.limit, output_dir=args.output_dir))
    except Exception:
        result = {"status": "attention", "error_code": "smoke_configuration_or_cleanup_failed", "orders_sent": 0}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
