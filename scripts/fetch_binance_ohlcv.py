#!/usr/bin/env python3
"""Baixa OHLCV público da Binance sem autenticação ou endpoints de trading."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests


URL = "https://api.binance.com/api/v3/klines"
COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_asset_volume", "number_of_trades", "taker_buy_base_volume",
    "taker_buy_quote_volume", "ignore",
]
INTERVAL_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
    "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000,
    "4h": 14_400_000, "6h": 21_600_000, "8h": 28_800_000,
    "12h": 43_200_000, "1d": 86_400_000, "3d": 259_200_000,
    "1w": 604_800_000,
}


def _request_page(session: requests.Session, params: dict, timeout: int) -> list:
    for attempt in range(4):
        response = session.get(
            URL,
            params=params,
            headers={"User-Agent": "ZIA-TRADER-public-ohlcv/1.1"},
            timeout=timeout,
        )
        if response.status_code in {418, 429, 500, 502, 503, 504}:
            retry_after = float(response.headers.get("Retry-After", "1"))
            time.sleep(min(8.0, retry_after * (attempt + 1)))
            continue
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            raise RuntimeError(f"Binance retornou erro público: {payload}")
        return payload
    raise RuntimeError("Binance não respondeu após tentativas de retry")


def fetch(
    symbol: str,
    interval: str,
    limit: int,
    timeout: int = 20,
    start_time_ms: int | None = None,
    end_time_ms: int | None = None,
) -> pd.DataFrame:
    if interval not in INTERVAL_MS:
        raise ValueError(f"intervalo não suportado pelo coletor: {interval}")
    if not 1 <= limit <= 100_000:
        raise ValueError("limit deve estar entre 1 e 100000")
    session = requests.Session()
    step = INTERVAL_MS[interval]
    now_ms = end_time_ms or int(datetime.now(timezone.utc).timestamp() * 1000)
    cursor_ms = start_time_ms if start_time_ms is not None else now_ms - limit * step
    pages: list[list] = []
    remaining = limit
    while remaining > 0:
        page_limit = min(1000, remaining)
        payload = _request_page(
            session,
            {"symbol": symbol.upper(), "interval": interval, "limit": page_limit, "startTime": cursor_ms, "endTime": now_ms},
            timeout,
        )
        if not payload:
            break
        pages.extend(payload)
        remaining = limit - len(pages)
        last_open_ms = int(payload[-1][0])
        next_cursor = last_open_ms + step
        if next_cursor <= cursor_ms:
            break
        cursor_ms = next_cursor
        if len(payload) < page_limit:
            break
        time.sleep(0.08)

    frame = pd.DataFrame(pages, columns=COLUMNS)
    if frame.empty:
        raise RuntimeError("Binance retornou dataset vazio")
    numeric = ["open", "high", "low", "close", "volume", "quote_asset_volume", "number_of_trades"]
    for column in numeric:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    frame["open_time"] = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
    frame["close_time"] = pd.to_datetime(frame["close_time"], unit="ms", utc=True)
    now = pd.Timestamp.now(tz="UTC")
    frame = frame[frame["close_time"] < now].copy()
    frame = frame.sort_values("open_time").drop_duplicates("open_time", keep="last")
    if frame["open_time"].duplicated().any():
        raise RuntimeError("duplicata de open_time após normalização")
    if not frame["open_time"].is_monotonic_increasing:
        raise RuntimeError("timestamps não estão em ordem crescente")
    return frame[["open_time", "open", "high", "low", "close", "volume"]].reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--limit", type=int, default=1000, help="número total de velas; o endpoint é paginado em blocos de 1000")
    parser.add_argument("--days", type=int, default=None, help="atalho para obter dias*velas_por_dia, respeitando --limit quando maior")
    parser.add_argument("--start-date", default=None, help="data UTC ISO-8601 inicial, por exemplo 2020-01-01T00:00:00Z")
    parser.add_argument("--end-date", default=None, help="data UTC ISO-8601 final; por padrão usa agora")
    parser.add_argument("--output", default="data/dataset_btcusdt_1h.csv")
    args = parser.parse_args()
    limit = args.limit
    start_time_ms = None
    end_time_ms = None
    if args.start_date:
        start_dt = datetime.fromisoformat(args.start_date.replace("Z", "+00:00"))
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        end_dt = datetime.fromisoformat((args.end_date or datetime.now(timezone.utc).isoformat()).replace("Z", "+00:00"))
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
        start_time_ms = int(start_dt.timestamp() * 1000)
        end_time_ms = int(end_dt.timestamp() * 1000)
        if end_time_ms <= start_time_ms:
            raise SystemExit("--end-date deve ser posterior a --start-date")
        candles = (end_time_ms - start_time_ms) // INTERVAL_MS[args.interval] + 1
        limit = max(limit, candles)
    if args.days is not None:
        if args.days <= 0:
            raise SystemExit("--days deve ser positivo")
        candles_per_day = max(1, 86_400_000 // INTERVAL_MS[args.interval])
        limit = max(limit, args.days * candles_per_day)
    frame = fetch(args.symbol, args.interval, limit, start_time_ms=start_time_ms, end_time_ms=end_time_ms)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False, date_format="%Y-%m-%dT%H:%M:%S.%fZ")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    print(json.dumps({
        "endpoint": URL,
        "symbol": args.symbol.upper(),
        "interval": args.interval,
        "rows": len(frame),
        "first_open_time": frame["open_time"].iloc[0].isoformat(),
        "last_open_time": frame["open_time"].iloc[-1].isoformat(),
        "duplicates": int(frame["open_time"].duplicated().sum()),
        "sha256": digest,
        "output": str(output),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2))


if __name__ == "__main__":
    main()
