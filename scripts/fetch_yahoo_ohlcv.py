"""Baixa OHLCV público Yahoo sem autenticação e sem endpoint de trading."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import httpx
import pandas as pd


BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart"


async def fetch_async(ticker: str, range_value: str = "60d", interval: str = "1h") -> pd.DataFrame:
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=5.0),
        limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        follow_redirects=False,
    ) as client:
        response = await client.get(
            f"{BASE_URL}/{ticker}",
            params={"range": range_value, "interval": interval, "events": "history"},
            headers={"User-Agent": "ZIA-Trader-public-readonly/1.1"},
        )
        response.raise_for_status()
        payload = response.json()
    result = payload.get("chart", {}).get("result", [])
    if not result:
        raise RuntimeError(f"Yahoo não retornou dados para {ticker}")
    chart = result[0]
    quote = (chart.get("indicators", {}).get("quote", [{}]) or [{}])[0]
    frame = pd.DataFrame({
        "open_time": pd.to_datetime(chart.get("timestamp", []), unit="s", utc=True),
        "open": quote.get("open", []),
        "high": quote.get("high", []),
        "low": quote.get("low", []),
        "close": quote.get("close", []),
        "volume": quote.get("volume", []),
    }).dropna(subset=["close"]).sort_values("open_time").drop_duplicates("open_time")
    if frame.empty:
        raise RuntimeError(f"Yahoo retornou série vazia para {ticker}")
    return frame.reset_index(drop=True)


def fetch(ticker: str, range_value: str = "60d", interval: str = "1h") -> pd.DataFrame:
    """Compatibilidade síncrona de CLI; o transporte é executado via AsyncClient."""
    return asyncio.run(fetch_async(ticker, range_value, interval))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", default="BTC-USD")
    parser.add_argument("--range", dest="range_value", default="60d")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    frame = fetch(args.ticker, args.range_value, args.interval)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False, date_format="%Y-%m-%dT%H:%M:%S.%fZ")
    print(json.dumps({"source": BASE_URL, "ticker": args.ticker, "interval": args.interval, "rows": len(frame), "output": str(output), "first": frame["open_time"].iloc[0].isoformat(), "last": frame["open_time"].iloc[-1].isoformat()}, indent=2))


if __name__ == "__main__":
    main()
