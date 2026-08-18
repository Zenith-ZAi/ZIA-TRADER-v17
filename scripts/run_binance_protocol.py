#!/usr/bin/env python3
"""Executa o protocolo de validação sobre OHLCV público baixado da Binance."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd

from config.settings import Settings
from core.backtest_engine import BacktestEngine
from core.market_signals import MarketSignalCache
from core.pullback_strategy import calculate_pullback_signal


def load_ohlcv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, parse_dates=["open_time"])
    frame = frame.rename(columns={"open_time": "timestamp"}).set_index("timestamp").sort_index()
    required = ["open", "high", "low", "close", "volume"]
    frame[required] = frame[required].apply(pd.to_numeric, errors="raise")
    return frame[required]


def write_events(frame: pd.DataFrame, path: Path) -> list[str]:
    indices = np.linspace(300, len(frame) - 300, 10, dtype=int)
    timestamps = [frame.index[int(index)].isoformat() for index in indices]
    path.write_text(json.dumps([{"name": f"SANDBOX_EVENT_{i + 1}", "timestamp": timestamp, "symbols": ["BTC/USDT"]} for i, timestamp in enumerate(timestamps)], indent=2), encoding="utf-8")
    return timestamps


def make_settings(events_file: Path) -> Settings:
    return Settings(
        PULLBACK_STRATEGY_ENABLED=True,
        FRICTION_ENABLED=True,
        FRICTION_SLEEP_ENABLED=False,
        FRICTION_MIN_LATENCY_MS=150.0,
        FRICTION_MAX_LATENCY_MS=500.0,
        FRICTION_MIN_SLIPPAGE_TICKS=0.5,
        FRICTION_MAX_SLIPPAGE_TICKS=2.0,
        FRICTION_COMMISSION_RATE=0.0005,
        FRICTION_SPREAD_PRICE=0.0,
        FRICTION_TICK_SIZE=0.01,
        FRICTION_SEED=42,
        BACKTEST_FEE_RATE=0.0,
        ECONOMIC_EVENTS_FILE=str(events_file),
        EVENT_BLOCK_BEFORE_SECONDS=60,
        EVENT_BLOCK_AFTER_SECONDS=300,
        BACKTEST_INITIAL_CAPITAL=10_000.0,
        MAX_RISK_PER_TRADE=0.02,
        MAX_EXPOSURE_PER_SYMBOL=0.10,
    )


def close_to_close_gap(frame: pd.DataFrame) -> pd.Series:
    return (frame["open"] / frame["close"].shift(1) - 1.0).abs().fillna(0.0)


def spoofing_check(frame: pd.DataFrame, settings: Settings, count: int = 5) -> dict:
    cache = MarketSignalCache(frame)
    candidates = []
    for index in range(250, len(frame)):
        signal = cache.at(index, min_confidence=settings.MIN_CONFIDENCE_THRESHOLD, max_volatility=settings.BACKTEST_MAX_VOLATILITY)
        if signal.candidate_action in {"buy", "sell"}:
            candidates.append((index, signal.candidate_action))
        if len(candidates) >= count:
            break
    scenarios = []
    for index, direction in candidates:
        spoof = frame.iloc[: index + 1].copy()
        row = spoof.iloc[-1].copy()
        row["volume"] = float(row["volume"]) * 4.0
        if direction == "buy":
            row["close"] = float(row["open"]) * 0.995
            row["high"] = max(float(row["high"]), float(row["open"]))
        else:
            row["close"] = float(row["open"]) * 1.005
            row["low"] = min(float(row["low"]), float(row["open"]))
        spoof.iloc[-1] = row
        signal = calculate_pullback_signal(
            spoof,
            ema_period=settings.PULLBACK_EMA_PERIOD,
            rsi_period=settings.PULLBACK_RSI_PERIOD,
            atr_period=settings.PULLBACK_ATR_PERIOD,
            volume_period=settings.PULLBACK_VOLUME_PERIOD,
            exhaustion_volume_ratio=settings.PULLBACK_EXHAUSTION_VOLUME_RATIO,
            trigger_volume_ratio=settings.PULLBACK_TRIGGER_VOLUME_RATIO,
        )
        scenarios.append({"index": index, "candidate": direction, "result": signal.action, "filtered": signal.action == "hold"})
    return {"requested": count, "scenarios": scenarios, "pass": len(scenarios) == count and all(item["filtered"] for item in scenarios)}


async def run_protocol(dataset: Path, events_file: Path) -> dict:
    started = time.perf_counter()
    frame = load_ohlcv(dataset)
    settings = make_settings(events_file)
    engine = BacktestEngine(settings, None)
    full = await engine.run("BTC/USDT", frame, "Pullback LTA/LTB + fricção pública")

    returns = frame["close"].pct_change()
    rolling_vol = returns.rolling(24, min_periods=24).std()
    low_threshold = rolling_vol.quantile(1 / 3)
    high_threshold = rolling_vol.quantile(2 / 3)
    range_frame = frame[rolling_vol <= low_threshold].dropna()
    turbulent_frame = frame[rolling_vol >= high_threshold].dropna()
    regime_results = {}
    for name, regime_frame in [("range_baixa_volatilidade", range_frame), ("turbulento_alta_volatilidade", turbulent_frame)]:
        if len(regime_frame) >= 250:
            regime_results[name] = await BacktestEngine(settings, None).run("BTC/USDT", regime_frame, name)
        else:
            regime_results[name] = {"status": "insufficient_data", "rows": len(regime_frame)}

    gap_frame = frame.copy()
    gap_injections = []
    for trade in full.get("trades", [])[:5]:
        try:
            entry_position = int(frame.index.get_loc(pd.Timestamp(trade["entry_index"])))
        except (KeyError, TypeError, ValueError):
            continue
        target_position = entry_position + 1
        if target_position >= len(gap_frame):
            continue
        factor = 0.98 if trade["action"] == "buy" else 1.02
        previous_close = float(gap_frame["close"].iloc[entry_position])
        gap_open = previous_close * factor
        gap_frame.iloc[target_position, gap_frame.columns.get_loc("open")] = gap_open
        gap_frame.iloc[target_position, gap_frame.columns.get_loc("close")] = gap_open
        gap_frame.iloc[target_position, gap_frame.columns.get_loc("high")] = max(gap_open, previous_close) if trade["action"] == "buy" else gap_open * 1.01
        gap_frame.iloc[target_position, gap_frame.columns.get_loc("low")] = gap_open * 0.99 if trade["action"] == "buy" else min(gap_open, previous_close)
        gap_injections.append({"entry_index": trade["entry_index"], "gap_index": gap_frame.index[target_position].isoformat(), "action": trade["action"], "gap_pct": factor - 1.0})
    gap_results = await BacktestEngine(settings, None).run("BTC/USDT", gap_frame, "gaps sintéticos de 2%")

    result = {
        "dataset": {
            "path": str(dataset),
            "rows": len(frame),
            "first_timestamp": frame.index[0].isoformat(),
            "last_timestamp": frame.index[-1].isoformat(),
            "duplicates": int(frame.index.duplicated().sum()),
            "missing_values": int(frame.isna().sum().sum()),
            "ohlcv_valid": bool((frame["high"] >= frame[["open", "close"]].max(axis=1)).all() and (frame["low"] <= frame[["open", "close"]].min(axis=1)).all()),
            "max_observed_gap_pct": float(close_to_close_gap(frame).max()),
        },
        "full_backtest": full,
        "regimes": regime_results,
        "gap_stress": {"injections": gap_injections, "metrics": gap_results},
        "spoofing": spoofing_check(frame, settings),
        "tick_protocol": {
            "status": "not_tested",
            "reason": "A API pública usada fornece klines; o anexo exige replay tick-a-tick e 2,3 milhões de ticks, que não foram inventados.",
        },
        "approval": {
            "net_profit_positive": bool(full.get("total_pnl", 0.0) > 0),
            "max_drawdown_under_15pct_full": bool(full.get("max_drawdown", 0.0) > -0.15),
            "max_drawdown_under_15pct_gap": bool(gap_results.get("max_drawdown", 0.0) > -0.15),
            "sharpe_over_1_full": bool(full.get("sharpe_ratio", 0.0) > 1.0),
            "spoofing_filtered": bool(spoofing_check(frame, settings)["pass"]),
            "dataset_integrity": bool(frame.index.is_monotonic_increasing and not frame.index.duplicated().any()),
        },
        "elapsed_seconds": time.perf_counter() - started,
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="data/dataset_btcusdt_1h_2020_2024.csv")
    parser.add_argument("--events", default="data/protocol_events.json")
    parser.add_argument("--output", default="data/binance_protocol_result.json")
    args = parser.parse_args()
    dataset = Path(args.dataset)
    events = Path(args.events)
    events.parent.mkdir(parents=True, exist_ok=True)
    frame = load_ohlcv(dataset)
    event_times = write_events(frame, events)
    result = asyncio.run(run_protocol(dataset, events))
    result["synthetic_event_timestamps"] = event_times
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
