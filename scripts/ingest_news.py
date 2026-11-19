#!/usr/bin/env python3
"""Ingere notícias/tendências opt-in, sem endpoints de trading ou saída de segredos."""
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

from sqlalchemy import func, select

from config.settings import Settings
from data.news_processor import NewsProcessor
from database import NewsArticle, TrendSnapshot
from database_manager import DatabaseManager


def _stored_counts(db: DatabaseManager) -> dict[str, int]:
    with db.SessionLocal() as session:
        return {
            "news_articles_total": session.scalar(select(func.count()).select_from(NewsArticle)),
            "trend_snapshots_total": session.scalar(select(func.count()).select_from(TrendSnapshot)),
        }


async def run(symbols: list[str], database_url: str) -> dict:
    settings = Settings(DATABASE_URL=database_url)
    db = DatabaseManager(database_url)
    processor = NewsProcessor(settings, db)
    try:
        await asyncio.to_thread(db.create_tables)
        articles = await processor.fetch_all(symbols)
        trends = await processor.fetch_trending(symbols)
        stored = await asyncio.to_thread(_stored_counts, db)
        return {
            "symbols": symbols,
            "database_dialect": db.engine.dialect.name,
            "articles_processed": len(articles),
            "articles_by_provider": dict(Counter(str(article.get("provider") or article.get("source") or "unknown") for article in articles)),
            "trends_processed": len(trends),
            "stored_row_counts": stored,
            "persistence_note": "Totals describe stored rows, not new rows or a guarantee that every processed item persisted.",
            "providers": processor.health(),
            "sentiment": processor.aggregate_sentiment(articles),
            "trend_score": processor.aggregate_trend_score(trends),
            "orders_sent": 0,
        }
    finally:
        try:
            await processor.aclose()
        finally:
            await asyncio.to_thread(db.engine.dispose)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=["BTC/USDT", "ETH/USDT", "SOL/USDT"])
    parser.add_argument("--database-url", default=None, help="Prefer DATABASE_URL via ambiente/secret file; não use senha na linha de comando.")
    args = parser.parse_args()
    # Read runtime configuration only here; no complete Settings serialization.
    database_url = args.database_url or Settings().DATABASE_URL
    try:
        result = asyncio.run(run(args.symbols, database_url))
    except Exception:
        print(json.dumps({"status": "attention", "error_code": "news_ingestion_unavailable", "orders_sent": 0}))
        raise SystemExit(1)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
