#!/usr/bin/env python3
"""Executa um ciclo curto do motor com OHLCV público real e autonomia desligada."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from config.settings import Settings
from core.engine import RoboTraderUnified
from data.news_processor import NewsProcessor
from database_manager import DatabaseManager
from execution.exchange_connector import ExchangeConnector


class PublicOHLCVReplay:
    def __init__(self, frame: pd.DataFrame):
        self.frame = frame.sort_index()
        self.is_connected = False

    async def connect(self):
        self.is_connected = True

    async def close(self):
        self.is_connected = False

    async def get_historical_data(self, symbol: str, timeframe: str, limit: int = 100) -> pd.DataFrame:
        return self.frame.tail(limit).copy()

    async def get_market_data(self, symbol: str) -> dict:
        row = self.frame.iloc[-1]
        return {
            "symbol": symbol,
            "last": float(row["close"]),
            "bid": float(row["close"]),
            "ask": float(row["close"]),
            "volume": float(row["volume"]),
            "timestamp": self.frame.index[-1].isoformat(),
        }

    async def get_order_book(self, symbol: str, limit: int = 20) -> dict:
        return {"symbol": symbol, "bids": [], "asks": [], "limit": limit}

    async def get_account_balance(self) -> dict:
        return {"USDT": 10000.0, "BTC": 0.0}

    async def place_order(self, *args, **kwargs):
        raise RuntimeError("Replay shadow: place_order bloqueado")


async def main(dataset: str, database_url: str, symbol: str) -> dict:
    frame = pd.read_csv(dataset, parse_dates=["open_time"]).set_index("open_time").sort_index()
    frame = frame[["open", "high", "low", "close", "volume"]].tail(600)
    settings = Settings(
        BINANCE_MODE="simulated",
        DATABASE_URL=database_url,
        SYMBOLS=[symbol],
        SHADOW_MODE_ENABLED=True,
        AUTONOMOUS_TRADING_ENABLED=False,
        NEURAL_MODELS_ENABLED=False,
        PULLBACK_STRATEGY_ENABLED=False,
        TRADING_LOOP_INTERVAL=1,
        NEWS_HTTP_TIMEOUT_SECONDS=1,
    )
    db = DatabaseManager(database_url)
    db.create_tables()
    processor = NewsProcessor(settings, db)
    connector = ExchangeConnector(settings)
    connector._adapter = PublicOHLCVReplay(frame)
    engine = RoboTraderUnified(settings, processor, connector, db)
    try:
        await asyncio.wait_for(engine.start(), timeout=15.0)
    except asyncio.TimeoutError:
        engine.is_running = False
    records = db.get_ai_observations(symbol, limit=100)
    return {
        "symbol": symbol,
        "bars_replayed": len(frame),
        "orders_sent": 0,
        "observations_created_or_available": len(records),
        "latest_action": records[0].action if records else "none",
        "latest_news_sentiment": records[0].news_sentiment if records else 0.0,
        "latest_trend_score": records[0].trend_score if records else 0.0,
    }


def cli() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset")
    parser.add_argument("--database-url", default="sqlite:///./data/zia_trader.db")
    parser.add_argument("--symbol", default="BTC/USDT")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(main(args.dataset, args.database_url, args.symbol)), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    cli()
