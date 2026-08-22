"""Replay seguro de 60 barras para validar crypto e Forex sem enviar ordens."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import Settings
from core.engine import RoboTraderUnified
from database_manager import DatabaseManager
from data.news_processor import NewsProcessor
from execution.forex_adapter import ForexPaperAdapter
from execution.market_connector import MarketConnector, MarketConnectorError


class ReplayNewsProcessor:
    async def fetch_all(self, symbols):
        return []

    async def fetch_trending(self, symbols):
        return []

    def aggregate_sentiment(self, articles):
        return 0.0

    def health(self):
        return {"replay": {"ok": True, "source": "no-news-replay"}}

    async def close(self):
        return None


class ReplayConnector:
    def __init__(self, frame: pd.DataFrame, symbol: str, cycles: int = 60, market: str = "crypto"):
        self.frame = frame.sort_index().copy()
        self.symbol = symbol
        self.cycles_target = int(cycles)
        self.market = market
        self.cursor = max(40, min(len(self.frame) - self.cycles_target - 1, 200))
        self.active_index = self.cursor
        self.cycles = 0
        self.is_connected = False
        self.cycle_started: list[float] = []
        self.cycle_intervals: list[float] = []
        self.previous_cycle_start: float | None = None
        self.done = asyncio.Event()

    async def connect(self):
        self.is_connected = True

    async def close(self):
        self.is_connected = False

    async def get_historical_data(self, symbol, timeframe, limit=100):
        if self.cycles >= self.cycles_target:
            self.done.set()
            return self.frame.iloc[: self.active_index + 1].tail(limit).copy()
        now = time.perf_counter()
        if self.previous_cycle_start is not None:
            self.cycle_intervals.append(now - self.previous_cycle_start)
        self.previous_cycle_start = now
        self.cycle_started.append(now)
        self.active_index = min(self.cursor, len(self.frame) - 1)
        self.cursor += 1
        self.cycles += 1
        if self.cycles >= self.cycles_target:
            self.done.set()
        return self.frame.iloc[: self.active_index + 1].tail(limit).copy()

    async def get_market_data(self, symbol):
        row = self.frame.iloc[self.active_index]
        close = float(row["close"])
        spread = close * (0.00002 if self.market == "crypto" else 0.00005)
        return {
            "symbol": symbol,
            "last": close,
            "bid": close - spread / 2.0,
            "ask": close + spread / 2.0,
            "high": float(row.get("high", close)),
            "low": float(row.get("low", close)),
            "volume": float(row.get("volume", 1.0)),
            "timestamp": self.frame.index[self.active_index].isoformat(),
        }

    async def get_order_book(self, symbol, limit=20):
        market = await self.get_market_data(symbol)
        depth = 1000.0 if self.market == "crypto" else 100000.0
        return {
            "symbol": symbol,
            "bids": [[market["bid"], depth]],
            "asks": [[market["ask"], depth]],
            "limit": limit,
        }

    async def get_account_balance(self):
        return {"USDT": 10000.0, "BTC": 0.0} if self.market == "crypto" else {"USD": 10000.0}

    async def place_order(self, *args, **kwargs):
        raise RuntimeError("Upgrade2 replay: place_order bloqueado")

    async def normalize_order_values(self, symbol, quantity, price=None):
        result = {"quantity": float(quantity)}
        if price is not None:
            result["price"] = float(price)
        return result


def load_crypto(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, parse_dates=["open_time"]).set_index("open_time").sort_index()
    return frame[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce").dropna()


async def load_forex(limit: int = 120) -> tuple[pd.DataFrame, str]:
    settings = Settings(MARKET_ADAPTER="forex", FOREX_MODE="public", NEWS_HTTP_TIMEOUT_SECONDS=8)
    connector = MarketConnector(settings)
    try:
        await connector.connect()
        frame = await connector.get_historical_data("EURUSD", "1m", limit)
        await connector.close()
        return frame, "yahoo/forex-python-public"
    except Exception:
        try:
            paper = ForexPaperAdapter(Settings(FOREX_PAPER_SPREAD=0.0001))
            await paper.connect()
            frame = await paper.get_historical_data("EUR/USD", "1m", limit)
            await paper.close()
            return frame, "forex-paper-fallback"
        except Exception as exc:
            raise MarketConnectorError("não foi possível carregar replay Forex público ou paper") from exc


async def replay_market(frame: pd.DataFrame, symbol: str, market: str, database_url: str, cycles: int = 60) -> dict:
    settings = Settings(
        DATABASE_URL=database_url,
        SYMBOLS=[symbol],
        TIMEFRAME="1m" if market == "forex" else "1h",
        BINANCE_MODE="simulated",
        MARKET_ADAPTER="binance" if market == "crypto" else "forex",
        FOREX_MODE="paper",
        SHADOW_MODE_ENABLED=True,
        AUTONOMOUS_TRADING_ENABLED=False,
        NEURAL_MODELS_ENABLED=False,
        PULLBACK_STRATEGY_ENABLED=False,
        MULTI_TIMEFRAME_ENABLED=False,
        NEWS_FAIL_CLOSED_FOR_ENTRY=False,
        COST_AWARE_EXECUTION_ENABLED=True,
        TRADING_LOOP_INTERVAL=0,
        ERROR_RETRY_INTERVAL=0,
    )
    db = DatabaseManager(database_url)
    db.create_tables()
    connector = ReplayConnector(frame, symbol, cycles=cycles, market=market)
    processor = ReplayNewsProcessor()
    engine = RoboTraderUnified(settings, processor, connector, db)
    started = time.perf_counter()
    task = asyncio.create_task(engine.start())
    try:
        await asyncio.wait_for(connector.done.wait(), timeout=15.0)
    finally:
        engine.is_running = False
        await asyncio.wait_for(task, timeout=5.0)
    elapsed = time.perf_counter() - started
    observations = db.get_ai_observations(symbol, limit=cycles + 5)
    intervals = [value * 1000.0 for value in connector.cycle_intervals if value > 0]

    return {
        "market": market,
        "symbol": symbol,
        "bars_replayed": min(connector.cycles, cycles),
        "simulated_operation_hours": 1,
        "orders_sent": 0,
        "observations": len(observations),
        "elapsed_seconds": elapsed,
        "cycle_latency_ms": {
            "p50": float(np.percentile(intervals, 50)) if intervals else 0.0,
            "p95": float(np.percentile(intervals, 95)) if intervals else 0.0,
            "max": float(max(intervals)) if intervals else 0.0,
            "samples": len(intervals),
            "under_200ms": bool(intervals and max(intervals) < 200.0),
        },
        "latest_action": observations[0].action if observations else "none",
        "news_source": processor.health(),
    }


async def run(crypto_dataset: Path, output: Path) -> dict:
    crypto = await replay_market(load_crypto(crypto_dataset), "BTC/USDT", "crypto", "sqlite:///:memory:")
    forex_frame, forex_source = await load_forex(120)
    forex = await replay_market(forex_frame, "EUR/USD", "forex", "sqlite:///:memory:")
    forex["data_source"] = forex_source
    result = {"protocol": "Promptdeupgrade2", "mode": "replay_shadow", "orders_sent": 0, "crypto": crypto, "forex": forex}
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--crypto-dataset", default="data/dataset_btcusdt_1h_2020_2024.csv")
    parser.add_argument("--output", default="data/upgrade2_replay_result.json")
    args = parser.parse_args()
    result = asyncio.run(run(Path(args.crypto_dataset), Path(args.output)))
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
