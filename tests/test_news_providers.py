import asyncio

from config.settings import Settings
from data.news_processor import NewsProcessor


def test_optional_news_providers_are_normalized(monkeypatch):
    settings = Settings(
        MARKETAUX_API_KEY="marketaux-test",
        FINNHUB_API_KEY="finnhub-test",
        TWELVE_DATA_API_KEY="twelve-test",
        NEWS_PROVIDER_ARTICLES=5,
        NEWS_MAX_ARTICLES=10,
        MARKETAUX_BASE_URL="https://test.local/marketaux",
        FINNHUB_BASE_URL="https://test.local/finnhub",
        TWELVE_DATA_BASE_URL="https://test.local/twelve",
    )
    processor = NewsProcessor(settings)

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def fake_get(url, params, headers, timeout):
        if "marketaux" in url:
            return FakeResponse({"data": [{"uuid": "m-1", "title": "Bitcoin growth", "description": "positive", "url": "https://m/1", "published_at": "2026-08-18T10:00:00Z", "entities": [{"symbol": "BTC", "sentiment_score": 0.8}]}]})
        if "finnhub" in url:
            return FakeResponse([{"id": 7, "headline": "Crypto falls", "summary": "negative", "url": "https://f/1", "datetime": 1787047200, "related": "BTC", "source": "test"}])
        return FakeResponse({"values": [{"id": "t-1", "title": "BTC market update", "summary": "neutral", "url": "https://t/1", "datetime": "2026-08-18 10:00:00", "symbol": "BTC/USDT"}]})

    monkeypatch.setattr("data.news_processor.requests.get", fake_get)
    async def run():
        return await asyncio.gather(
            processor.fetch_marketaux_news(["BTC/USDT"]),
            processor.fetch_finnhub_news(["BTC/USDT"]),
            processor.fetch_twelve_data_news(["BTC/USDT"]),
        )

    marketaux, finnhub, twelve = asyncio.run(run())
    assert marketaux[0]["provider"] == "Marketaux"
    assert marketaux[0]["sentiment_score"] == 0.8
    assert finnhub[0]["provider"] == "Finnhub"
    assert finnhub[0]["ticker"] == "BTC"
    assert twelve[0]["provider"] == "TwelveData"
    assert twelve[0]["ticker"] == "BTC/USDT"
    assert set(processor.health()) == {"marketaux", "finnhub", "twelve_data"}


def test_trend_score_uses_directional_change_only():
    assert NewsProcessor.aggregate_trend_score([{"trend_score": 1.0}]) == 0.0
    assert NewsProcessor.aggregate_trend_score([{"price_change_24h": 5.0}]) == 0.5
    assert NewsProcessor.aggregate_trend_score([{"price_change_24h": -20.0}]) == -1.0


def test_news_provider_errors_degrade_without_fabricating(monkeypatch):
    settings = Settings(MARKETAUX_API_KEY="marketaux-test", MARKETAUX_BASE_URL="https://test.local/marketaux")
    processor = NewsProcessor(settings)

    def failing_get(url, params, headers, timeout):
        raise TimeoutError("provider timeout")

    monkeypatch.setattr("data.news_processor.requests.get", failing_get)
    assert asyncio.run(processor.fetch_marketaux_news(["BTC/USDT"])) == []
    assert processor.health()["marketaux"]["ok"] is False
