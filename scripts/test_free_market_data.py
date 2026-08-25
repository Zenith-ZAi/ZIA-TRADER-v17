"""Testa dados públicos read-only sem chaves e sem endpoints de ordem."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import Settings
from execution.market_connector import MarketConnector
from scripts.fetch_binance_ohlcv import fetch as fetch_binance
from scripts.fetch_yahoo_ohlcv import fetch as fetch_yahoo


def _frame_summary(frame) -> dict[str, object]:
    time_values = frame["open_time"] if "open_time" in frame.columns else frame.index
    first = time_values.iloc[0] if hasattr(time_values, "iloc") else time_values[0]
    last = time_values.iloc[-1] if hasattr(time_values, "iloc") else time_values[-1]
    duplicates = int(time_values.duplicated().sum()) if hasattr(time_values, "duplicated") else int(frame.index.duplicated().sum())
    return {
        "rows": int(len(frame)),
        "first": first.isoformat() if hasattr(first, "isoformat") else str(first),
        "last": last.isoformat() if hasattr(last, "isoformat") else str(last),
        "duplicates": duplicates,
        "columns": list(frame.columns),
    }


async def _connector_summary(adapter_name: str, symbol: str, settings: Settings) -> dict[str, object]:
    connector = MarketConnector(settings)
    try:
        await connector.connect()
        history = await connector.get_historical_data(symbol, "1d", limit=80)
        market = await connector.get_market_data(symbol)
        order_book = await connector.get_order_book(symbol, limit=5)
        return {
            "adapter": adapter_name,
            "symbol": symbol,
            "history": _frame_summary(history),
            "market_fields": sorted(market.keys()),
            "read_only": bool(market.get("read_only", False) or order_book.get("read_only", False)),
            "order_book_levels": len(order_book.get("bids", [])) + len(order_book.get("asks", [])),
            "orders_sent": 0,
        }
    finally:
        await connector.close()


def main() -> None:
    results: list[dict[str, object]] = []
    for label, operation in (
        ("binance_public", lambda: fetch_binance("BTCUSDT", "1h", 120, timeout=15)),
        ("yahoo_global", lambda: fetch_yahoo("AAPL", "5d", "1h")),
    ):
        try:
            results.append({"source": label, "ok": True, "summary": _frame_summary(operation())})
        except Exception as exc:
            results.append({"source": label, "ok": False, "error": str(exc)})

    async def adapters() -> list[dict[str, object]]:
        output = []
        for label, symbol, settings in (
            ("yahoo_b3", "PETR4", Settings(MARKET_ADAPTER="b3", NEWS_HTTP_TIMEOUT_SECONDS=15)),
            ("forex_public", "EUR/USD", Settings(MARKET_ADAPTER="forex", FOREX_MODE="public", NEWS_HTTP_TIMEOUT_SECONDS=15)),
        ):
            try:
                output.append({"source": label, "ok": True, "summary": await _connector_summary(label, symbol, settings)})
            except Exception as exc:
                output.append({"source": label, "ok": False, "error": str(exc), "orders_sent": 0})
        return output

    results.extend(asyncio.run(adapters()))
    print(json.dumps({
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "mode": "public_read_only",
        "orders_sent": 0,
        "results": results,
    }, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
