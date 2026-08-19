#!/usr/bin/env python3
"""Mede latência local de componentes do agente com OHLCV público real."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from ai.ensemble_model import EnsembleModel
from ai.feature_pipeline import build_feature_frame
from ai.whale_detector import WhaleDetector
from config.settings import Settings
from core.market_signals import calculate_market_signal
from core.pullback_strategy import PullbackSignalCache, calculate_pullback_signal


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return ordered[index]


def measure(name: str, function, repetitions: int) -> dict:
    samples = []
    for _ in range(repetitions):
        started = time.perf_counter_ns()
        function()
        samples.append((time.perf_counter_ns() - started) / 1_000_000.0)
    return {
        "component": name,
        "runs": repetitions,
        "min_ms": min(samples),
        "p50_ms": percentile(samples, 0.50),
        "p95_ms": percentile(samples, 0.95),
        "p99_ms": percentile(samples, 0.99),
        "max_ms": max(samples),
        "mean_ms": statistics.fmean(samples),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset")
    parser.add_argument("--model-dir", default="models")
    parser.add_argument("--runs", type=int, default=100)
    parser.add_argument("--output", default="data/latency_benchmark.json")
    args = parser.parse_args()

    frame = pd.read_csv(args.dataset, parse_dates=["open_time"]).set_index("open_time").sort_index().tail(600)
    settings = Settings(
        PULLBACK_STRATEGY_ENABLED=True,
        ENSEMBLE_MODEL_DIR=args.model_dir,
        NEWS_HTTP_TIMEOUT_SECONDS=1,
    )
    features = build_feature_frame(frame).dropna()
    model = EnsembleModel(args.model_dir)
    whale = WhaleDetector(settings, None)
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
    order_flow = {"symbol": "BTC/USDT", "buys": [], "sells": []}
    pullback_cache = PullbackSignalCache(frame, **pullback_kwargs)
    cached_pullback = pullback_cache.at(len(frame) - 1)

    def local_decision() -> None:
        local_features = build_feature_frame(frame).dropna()
        if model.is_trained and not local_features.empty:
            model.predict(local_features.tail(1))
        calculate_market_signal(frame, min_confidence=settings.MIN_CONFIDENCE_THRESHOLD, max_volatility=settings.BACKTEST_MAX_VOLATILITY, pullback_kwargs=pullback_kwargs)
        whale.detect_whale_activity(frame, order_flow)

    def local_decision_cached() -> None:
        local_features = build_feature_frame(frame).dropna()
        if model.is_trained and not local_features.empty:
            model.predict(local_features.tail(1))
        calculate_market_signal(frame, min_confidence=settings.MIN_CONFIDENCE_THRESHOLD, max_volatility=settings.BACKTEST_MAX_VOLATILITY, precomputed_pullback=cached_pullback)
        whale.detect_whale_activity(frame, order_flow)

    results = [
        measure("causal_feature_frame", lambda: build_feature_frame(frame).dropna(), args.runs),
        measure("ensemble_predict", lambda: model.predict(features.tail(1)) if model.is_trained and not features.empty else None, args.runs),
        measure("pullback_cache_build", lambda: PullbackSignalCache(frame, **pullback_kwargs), args.runs),
        measure("market_signal_with_pullback", lambda: calculate_market_signal(frame, min_confidence=settings.MIN_CONFIDENCE_THRESHOLD, max_volatility=settings.BACKTEST_MAX_VOLATILITY, pullback_kwargs=pullback_kwargs), args.runs),
        measure("market_signal_cached_pullback", lambda: calculate_market_signal(frame, min_confidence=settings.MIN_CONFIDENCE_THRESHOLD, max_volatility=settings.BACKTEST_MAX_VOLATILITY, precomputed_pullback=cached_pullback), args.runs),
        measure("pullback_only", lambda: calculate_pullback_signal(frame, **pullback_kwargs), args.runs),
        measure("whale_empty_book_baseline", lambda: whale.detect_whale_activity(frame, order_flow), args.runs),
        measure("combined_local_decision", local_decision, args.runs),
        measure("combined_local_decision_cached", local_decision_cached, args.runs),
    ]
    result = {
        "dataset": {"rows": len(frame), "start": frame.index[0].isoformat(), "end": frame.index[-1].isoformat()},
        "model_trained": bool(model.is_trained),
        "runs": args.runs,
        "units": "milliseconds; perf_counter_ns; local process only",
        "network_and_exchange": "not measured by this benchmark; Binance REST/WebSocket, TLS, routing, queueing and matching-engine latency are outside the local decision timer",
        "results": results,
    }
    Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
