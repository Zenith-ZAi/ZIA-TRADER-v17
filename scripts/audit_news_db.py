#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import NewsArticle, TrendSnapshot


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default="sqlite:///./data/zia_trader.db")
    args = parser.parse_args()
    engine = create_engine(args.database_url, connect_args={"check_same_thread": False} if "sqlite" in args.database_url else {})
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        articles = session.query(NewsArticle).all()
        trends = session.query(TrendSnapshot).all()
        print(json.dumps({
            "news_articles": len(articles),
            "news_providers": dict(Counter(article.provider for article in articles)),
            "news_symbols": dict(Counter(article.symbol or "unknown" for article in articles)),
            "trend_snapshots": len(trends),
            "trend_providers": dict(Counter(snapshot.provider for snapshot in trends)),
            "trend_symbols": dict(Counter(snapshot.symbol for snapshot in trends)),
            "sentiment_mean": float(sum(article.sentiment_score or 0.0 for article in articles) / len(articles)) if articles else 0.0,
        }, indent=2, ensure_ascii=False))
    finally:
        session.close()


if __name__ == "__main__":
    main()
