#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from config.settings import Settings
from core.backtest_engine import BacktestEngine


def main() -> None:
    dataset = Path(sys.argv[1] if len(sys.argv) > 1 else "data/dataset_btcusdt_1h_2020_2024.csv")
    events = Path(sys.argv[2] if len(sys.argv) > 2 else "data/protocol_events.json")
    frame = pd.read_csv(dataset, parse_dates=["open_time"]).set_index("open_time").sort_index()
    frame = frame[["open", "high", "low", "close", "volume"]]
    common = dict(
        FRICTION_ENABLED=True,
        FRICTION_SLEEP_ENABLED=False,
        FRICTION_COMMISSION_RATE=0.0005,
        FRICTION_TICK_SIZE=0.01,
        FRICTION_SEED=42,
        BACKTEST_FEE_RATE=0.0,
        ECONOMIC_EVENTS_FILE=str(events),
        BACKTEST_INITIAL_CAPITAL=10_000.0,
        MAX_RISK_PER_TRADE=0.02,
        MAX_EXPOSURE_PER_SYMBOL=0.10,
    )
    pullback = asyncio.run(BacktestEngine(Settings(PULLBACK_STRATEGY_ENABLED=True, **common), None).run("BTC/USDT", frame, "pullback"))
    baseline = asyncio.run(BacktestEngine(Settings(PULLBACK_STRATEGY_ENABLED=False, **common), None).run("BTC/USDT", frame, "deterministic"))
    output = {"pullback": pullback, "deterministic_without_pullback": baseline}
    print(json.dumps(output, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
