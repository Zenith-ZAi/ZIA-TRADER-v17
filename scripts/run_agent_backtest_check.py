#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import Settings
from core.backtest_engine import BacktestEngine


async def run_case(frame: pd.DataFrame, use_memory: bool) -> dict:
    settings = Settings(
        FRICTION_ENABLED=True,
        FRICTION_SLEEP_ENABLED=False,
        PULLBACK_STRATEGY_ENABLED=True,
        PATTERN_MEMORY_ENABLED=use_memory,
        BACKTEST_WARMUP_BARS=250,
        BACKTEST_USE_ENSEMBLE=False,
    )
    result = await BacktestEngine(settings, None).run("BTC/USDT", frame, "Prompt agent audit")
    return {
        "pattern_memory_enabled": use_memory,
        "trades_executed": result.get("trades_executed", 0),
        "total_pnl": result.get("total_pnl", 0.0),
        "return_pct": result.get("return_pct", 0.0),
        "sharpe_ratio": result.get("sharpe_ratio", 0.0),
        "max_drawdown": result.get("max_drawdown", 0.0),
        "win_rate": result.get("win_rate", 0.0),
        "profit_factor": result.get("profit_factor", 0.0),
        "pattern_rejections": result.get("pattern_rejections", 0),
        "ensemble_rejections": result.get("ensemble_rejections", 0),
        "blocked_event_candidates": result.get("blocked_event_candidates", 0),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset")
    parser.add_argument("--output", default="data/agent_backtest_check.json")
    args = parser.parse_args()
    frame = pd.read_csv(args.dataset, parse_dates=["open_time"]).set_index("open_time").sort_index()
    results = {
        "dataset_rows": len(frame),
        "start": frame.index[0].isoformat(),
        "end": frame.index[-1].isoformat(),
        "cases": [asyncio.run(run_case(frame, False)), asyncio.run(run_case(frame, True))],
        "orders_sent": 0,
        "note": "Memória habilitada sem registros prévios não autoriza entradas; o caso mede o efeito do gate vazio.",
    }
    Path(args.output).write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
