"""Recalcula sinais de snapshots de backtest e verifica paridade determinística."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import Settings
from core.backtest_engine import BacktestEngine
from core.market_signals import MarketSignalCache
from database_manager import DatabaseManager


def load_dataset(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, parse_dates=["open_time"])
    frame = frame.set_index("open_time").sort_index()
    return frame[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="raise")


async def run_replay(dataset_path: Path, database_url: str, symbol: str, timeframe: str) -> dict[str, Any]:
    data = load_dataset(dataset_path)
    settings = Settings(
        DATABASE_URL=database_url,
        TIMEFRAME=timeframe,
        PULLBACK_STRATEGY_ENABLED=False,
        PATTERN_MEMORY_ENABLED=False,
        BACKTEST_USE_ENSEMBLE=False,
        SHADOW_MODE_ENABLED=True,
        AUTONOMOUS_TRADING_ENABLED=False,
        LIVE_TRADING_ENABLED=False,
        LIVE_MODE=False,
    )
    db = DatabaseManager(database_url)
    db.create_tables()
    await BacktestEngine(settings, db).run(symbol, data, "Decision Snapshot Parity")
    snapshots = db.list_decision_snapshots(symbol=symbol, limit=10_000)
    signal_cache = MarketSignalCache(data)
    mismatches: list[dict[str, Any]] = []
    checked = 0
    for snapshot in snapshots:
        before = snapshot.get("before_context") or {}
        index = before.get("bar_index")
        if index is None or not 0 <= int(index) < len(data):
            continue
        recalculated = signal_cache.at(
            int(index),
            min_confidence=float(settings.MIN_CONFIDENCE_THRESHOLD),
            max_volatility=float(settings.BACKTEST_MAX_VOLATILITY),
        )
        stored_signal = (before.get("market_signal") or {}).get("action")
        checked += 1
        if stored_signal != recalculated.action:
            mismatches.append({
                "snapshot_id": snapshot.get("snapshot_id"),
                "bar_index": int(index),
                "stored_action": stored_signal,
                "recalculated_action": recalculated.action,
            })
    return {
        "status": "passed" if checked > 0 and not mismatches else "attention",
        "dataset": str(dataset_path),
        "symbol": symbol,
        "timeframe": timeframe,
        "snapshots_available": len(snapshots),
        "snapshots_checked": checked,
        "mismatches": mismatches,
        "orders_sent": 0,
        "live_trading_enabled": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset")
    parser.add_argument("--database-url", default="sqlite:////tmp/zia_snapshot_parity.db")
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--output", default="reports/replay_decision_snapshots.json")
    args = parser.parse_args()
    result = asyncio.run(run_replay(Path(args.dataset), args.database_url, args.symbol, args.timeframe))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if result["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
