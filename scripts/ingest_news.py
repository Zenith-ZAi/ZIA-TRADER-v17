#!/usr/bin/env python3
"""Ingere notícias e tendências atuais no banco sem endpoints de trading."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import Settings
from data.news_processor import NewsProcessor
from database_manager import DatabaseManager


async def run(symbols: list[str], database_url: str) -> dict:
    settings = Settings(DATABASE_URL=database_url)
    db = DatabaseManager(database_url)
    db.create_tables()
    processor = NewsProcessor(settings, db)
    articles = await processor.fetch_all(symbols)
    trends = await processor.fetch_trending(symbols)
    return {
        "symbols": symbols,
        "database_url": database_url.split(":", 1)[0],
        "articles_persisted_or_updated": len(articles),
        "articles_by_provider": dict(Counter(str(article.get("provider") or article.get("source") or "unknown") for article in articles)),
        "trends_persisted_or_updated": len(trends),
        "providers": processor.health(),
        "sentiment": processor.aggregate_sentiment(articles),
        "trend_score": processor.aggregate_trend_score(trends),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=["BTC/USDT", "ETH/USDT", "SOL/USDT"])
    parser.add_argument("--database-url", default="sqlite:///./data/zia_trader.db")
    args = parser.parse_args()
    result = asyncio.run(run(args.symbols, args.database_url))
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
