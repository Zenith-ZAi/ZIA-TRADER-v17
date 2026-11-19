from __future__ import annotations

import asyncio
import time

import pytest

from config.settings import Settings
from data.news_processor import NewsProcessor
from database_manager import DatabaseManager


@pytest.mark.parametrize("helper,payload", [
    ("create_news_article", {"provider": "test", "title": "News", "url": "https://example.test/news", "sentiment_score": 0.1}),
    ("create_trend_snapshot", {"provider": "test", "symbol": "BTC", "trend_score": 0.1}),
])
def test_news_helper_closes_session_when_commit_fails(tmp_path, monkeypatch, helper, payload):
    db = DatabaseManager(f"sqlite:///{tmp_path / 'session.db'}")
    db.create_tables()
    original_factory = db.SessionLocal
    state = {"closed": 0}

    class TrackingSession:
        def __init__(self):
            self.session = original_factory()
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.session.close()
            state["closed"] += 1
        def __getattr__(self, name):
            return getattr(self.session, name)
        def commit(self):
            raise RuntimeError("dummy commit error")

    monkeypatch.setattr(db, "SessionLocal", TrackingSession)
    try:
        with pytest.raises(RuntimeError, match="dummy commit error"):
            getattr(db, helper)(payload)
        assert state["closed"] == 1
    finally:
        db.engine.dispose()


def test_news_persistence_runs_outside_event_loop_in_sequence():
    class Database:
        def __init__(self):
            self.saved = []
        def create_news_article(self, article):
            time.sleep(0.04)
            self.saved.append(article["title"])

    async def run():
        settings = Settings(_env_file=None, NEWS_MAX_ARTICLES=3)
        db = Database()
        processor = NewsProcessor(settings, db)
        async def articles(_):
            return [{"title": "one", "url": "https://example.test/1"}, {"title": "two", "url": "https://example.test/2"}]
        async def empty(_):
            return []
        processor.fetch_gdelt_news = articles
        for name in ("fetch_rss_news", "fetch_alpha_vantage_news", "fetch_marketaux_news", "fetch_finnhub_news",
                     "fetch_twelve_data_news", "fetch_benzinga_news", "fetch_newsapi_news", "fetch_cryptopanic_news"):
            setattr(processor, name, empty)
        try:
            task = asyncio.create_task(processor.fetch_all(["BTC/USDT"]))
            ticks = 0
            while not task.done():
                ticks += 1
                await asyncio.sleep(0.005)
            assert len(await task) == 2
            assert db.saved == ["one", "two"]
            assert ticks >= 4
        finally:
            await processor.aclose()

    asyncio.run(run())
