import asyncio

from config.settings import Settings
from data.news_processor import NewsProcessor
from database import NewsArticle, TrendSnapshot
from database_manager import DatabaseManager
from tests.fakes import FakeAsyncHTTP


def test_news_and_trends_are_persisted_idempotently(tmp_path):
    settings = Settings(
        DATABASE_URL=f"sqlite:///{tmp_path / 'news.db'}",
        GDELT_BASE_URL="https://test.local/gdelt",
        COINGECKO_BASE_URL="https://test.local/coingecko",
        NEWS_CACHE_TTL_SECONDS=300,
    )
    db = DatabaseManager(settings.DATABASE_URL)
    db.create_tables()

    def fake_get(url, params, headers):
        if "gdelt" in url:
            return {"articles": [{"title": "BTC growth", "url": "https://example.test/news/1", "seendate": "20260817T120000Z"}]}
        return {"coins": [{"item": {"symbol": "BTC", "name": "Bitcoin", "market_cap_rank": 1, "data": {}}}]}

    processor = NewsProcessor(settings, db, http_client=FakeAsyncHTTP(fake_get))
    asyncio.run(processor.fetch_all(["BTC/USDT"]))
    asyncio.run(processor.fetch_trending(["BTC/USDT"]))
    asyncio.run(processor.fetch_all(["BTC/USDT"]))

    session = db.SessionLocal()
    try:
        assert session.query(NewsArticle).count() == 1
        assert session.query(TrendSnapshot).count() == 1
    finally:
        session.close()
