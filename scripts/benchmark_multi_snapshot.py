"""Benchmark de decisão local sobre snapshots públicos previamente coletados."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from statistics import fmean
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import Settings
from core.feature_pipeline import FeaturePipeline
from core.market_signals import calculate_market_signal
from core.pullback_registry import PullbackCacheRegistry
from scripts.fetch_binance_ohlcv import fetch_async


async def collect_snapshots(symbols: list[str], intervals: list[str], limit: int) -> dict[tuple[str, str], pd.DataFrame]:
    semaphore = asyncio.Semaphore(4)

    async def one(symbol: str, interval: str):
        async with semaphore:
            return (symbol, interval), await fetch_async(symbol, interval, limit)

    results = await asyncio.gather(*(one(symbol, interval) for symbol in symbols for interval in intervals))
    return dict(results)


def benchmark(snapshots: dict[tuple[str, str], pd.DataFrame], repetitions: int = 3) -> dict[str, Any]:
    settings = Settings(
        PULLBACK_STRATEGY_ENABLED=True,
        SHADOW_MODE_ENABLED=True,
        AUTONOMOUS_TRADING_ENABLED=False,
        LIVE_TRADING_ENABLED=False,
        LIVE_MODE=False,
    )
    features = FeaturePipeline(settings)
    pullbacks = PullbackCacheRegistry()
    prepared: list[tuple[str, str, pd.DataFrame, dict[str, Any]]] = []
    for (symbol, interval), frame in snapshots.items():
        frame = frame.copy()
        frame["open_time"] = pd.to_datetime(frame["open_time"], utc=True)
        frame = frame.set_index("open_time").sort_index()
        feature_frame = features.build_features(frame)
        pullback_kwargs = {
            "ema_period": settings.PULLBACK_EMA_PERIOD,
            "rsi_period": settings.PULLBACK_RSI_PERIOD,
            "atr_period": settings.PULLBACK_ATR_PERIOD,
            "volume_period": settings.PULLBACK_VOLUME_PERIOD,
            "touch_tolerance": settings.PULLBACK_TOUCH_TOLERANCE,
            "exhaustion_volume_ratio": settings.PULLBACK_EXHAUSTION_VOLUME_RATIO,
            "trigger_volume_ratio": settings.PULLBACK_TRIGGER_VOLUME_RATIO,
            "stop_atr_multiple": settings.PULLBACK_STOP_ATR_MULTIPLE,
            "target_atr_multiple": settings.PULLBACK_TARGET_ATR_MULTIPLE,
            "breakeven_atr_trigger": settings.PULLBACK_BREAKEVEN_ATR_TRIGGER,
        }
        pullback = pullbacks.get(symbol, interval, frame, **pullback_kwargs).at(len(frame) - 1)
        prepared.append((symbol, interval, frame, {"features": feature_frame, "pullback": pullback, "kwargs": pullback_kwargs}))

    samples: list[float] = []
    per_snapshot: list[dict[str, Any]] = []
    for symbol, interval, frame, context in prepared:
        local_samples: list[float] = []
        for _ in range(max(1, int(repetitions))):
            started = time.perf_counter_ns()
            context["features"].dropna().tail(1)
            signal = calculate_market_signal(
                frame,
                min_confidence=settings.MIN_CONFIDENCE_THRESHOLD,
                max_volatility=settings.BACKTEST_MAX_VOLATILITY,
                precomputed_pullback=context["pullback"],
            )
            elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000.0
            local_samples.append(elapsed_ms)
            samples.append(elapsed_ms)
        per_snapshot.append({
            "symbol": symbol,
            "timeframe": interval,
            "runs": len(local_samples),
            "mean_ms": fmean(local_samples),
            "max_ms": max(local_samples),
        })
    average = fmean(samples) if samples else 0.0
    return {
        "status": "passed" if len(prepared) == 15 and average < 200.0 else "attention",
        "snapshots": len(prepared),
        "repetitions": repetitions,
        "average_decision_ms": average,
        "max_decision_ms": max(samples) if samples else 0.0,
        "target_average_ms": 200.0,
        "network_in_timer": False,
        "live_trading_enabled": False,
        "orders_sent": 0,
        "per_snapshot": per_snapshot,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT")
    parser.add_argument("--intervals", default="1h,4h,1d")
    parser.add_argument("--limit", type=int, default=120)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--output", default="reports/benchmark_multi_snapshot.json")
    args = parser.parse_args()
    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    intervals = [item.strip() for item in args.intervals.split(",") if item.strip()]
    result = benchmark(asyncio.run(collect_snapshots(symbols, intervals, args.limit)), args.repetitions)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if result["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
