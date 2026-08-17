import asyncio

from config.settings import Settings
from data.news_processor import NewsProcessor
from database import NewsArticle, TrendSnapshot
from database_manager import DatabaseManager


def test_news_and_trends_are_persisted_idempotently(monkeypatch, tmp_path):
    settings = Settings(
        DATABASE_URL=f"sqlite:///{tmp_path / 'news.db'}",
        GDELT_BASE_URL="https://test.local/gdelt",
        COINGECKO_BASE_URL="https://test.local/coingecko",
        NEWS_CACHE_TTL_SECONDS=300,
    )
    db = DatabaseManager(settings.DATABASE_URL)
    db.create_tables()
    processor = NewsProcessor(settings, db)

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def fake_get(url, params, headers, timeout):
        if "gdelt" in url:
            return FakeResponse({"articles": [{"title": "BTC growth", "url": "https://example.test/news/1", "seendate": "20260817T120000Z"}]})
        return FakeResponse({"coins": [{"item": {"symbol": "BTC", "name": "Bitcoin", "market_cap_rank": 1, "data": {}}}]})

    monkeypatch.setattr("data.news_processor.requests.get", fake_get)
    asyncio.run(processor.fetch_all(["BTC/USDT"]))
    asyncio.run(processor.fetch_trending(["BTC/USDT"]))
    asyncio.run(processor.fetch_all(["BTC/USDT"]))

    session = db.SessionLocal()
    try:
        assert session.query(NewsArticle).count() == 1
        assert session.query(TrendSnapshot).count() == 1
    finally:
        session.close()
