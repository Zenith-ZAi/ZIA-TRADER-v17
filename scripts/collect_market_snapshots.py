"""Coleta agendada de dados; não executa estratégia, treinamento ou ordens."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.dataset_integrity import sha256_frame, validate_ohlcv
from scripts.fetch_binance_ohlcv import fetch_async


async def _collect_one(symbol: str, interval: str, limit: int, output_dir: Path, semaphore: asyncio.Semaphore) -> dict[str, Any]:
    async with semaphore:
        frame = await fetch_async(symbol, interval, limit)
    integrity = validate_ohlcv(frame, timeframe=interval, require_closed=True, reject_gaps=False, min_coverage=0.95)
    dataset_hash = sha256_frame(frame)
    records = frame.copy()
    for column in records.columns:
        if pd.api.types.is_datetime64_any_dtype(records[column]):
            records[column] = records[column].map(lambda value: value.isoformat())
    payload = {
        "symbol": symbol.upper(),
        "timeframe": interval,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "dataset_sha256": dataset_hash,
        "integrity": integrity,
        "orders_sent": 0,
        "live_trading_enabled": False,
        "candles": records.to_dict(orient="records"),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{symbol.lower()}_{interval}.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
    temporary.replace(target)
    return {"symbol": symbol.upper(), "timeframe": interval, "path": str(target), "rows": len(frame), "sha256": dataset_hash, "integrity": integrity}


async def collect_once(symbols: list[str], intervals: list[str], limit: int, output_dir: Path, concurrency: int = 4) -> dict[str, Any]:
    semaphore = asyncio.Semaphore(max(1, int(concurrency)))
    specs = [
        (symbol.strip().upper(), interval.strip())
        for symbol in symbols if symbol.strip()
        for interval in intervals if interval.strip()
    ]
    tasks = [_collect_one(symbol, interval, limit, output_dir, semaphore) for symbol, interval in specs]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    snapshots: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    for (symbol, interval), result in zip(specs, results):
        key = f"{symbol}:{interval}"
        if isinstance(result, Exception):
            errors[key] = f"{type(result).__name__}: {result}"
        else:
            snapshots.append(result)
    return {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "snapshots": snapshots,
        "errors": errors,
        "orders_sent": 0,
        "live_trading_enabled": False,
    }


async def run_loop(symbols: list[str], intervals: list[str], limit: int, output_dir: Path, concurrency: int, once: bool, interval_seconds: int) -> None:
    while True:
        result = await collect_once(symbols, intervals, limit, output_dir, concurrency)
        print(json.dumps(result, ensure_ascii=False, default=str), flush=True)
        if once:
            return
        await asyncio.sleep(max(1, int(interval_seconds)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Atualiza snapshots OHLCV para o ciclo de decisão")
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT")
    parser.add_argument("--intervals", default="1h,4h")
    parser.add_argument("--limit", type=int, default=250)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--output-dir", default="data/market_snapshots")
    args = parser.parse_args()
    if args.limit <= 0:
        raise SystemExit("--limit deve ser positivo")
    asyncio.run(run_loop(
        [value for value in args.symbols.split(",") if value.strip()],
        [value for value in args.intervals.split(",") if value.strip()],
        args.limit,
        Path(args.output_dir),
        args.concurrency,
        args.once,
        args.interval_seconds,
    ))


if __name__ == "__main__":
    main()
