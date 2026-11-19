from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from api.runtime_services import health_payload
from config.settings import Settings
from core.news_gate import evaluate_news_gate
from data.news_processor import NewsProcessor
from database_manager import DatabaseManager
from tests.fakes import FakeAsyncHTTP


@pytest.fixture
def application(tmp_path):
    settings = Settings(_env_file=None, DATABASE_URL=f"sqlite:///{tmp_path}/health.db",
                        NEWS_ENABLED_KEYED_PROVIDERS=[], REQUIRE_PERSISTENT_DATABASE=False,
                        REQUIRE_PERSISTENT_REDIS=False, LIVE_TRADING_ENABLED=False,
                        LIVE_MODE=False, LIVE_KILL_SWITCH=True)
    db = DatabaseManager(settings.DATABASE_URL)
    db.create_tables()
    news = NewsProcessor(settings, http_client=FakeAsyncHTTP(lambda *_: {}))
    manager = SimpleNamespace(news_processor=news,
                              redis_cache=SimpleNamespace(health=lambda: {"persistent": False}),
                              exchange_connector=SimpleNamespace(is_connected=False))
    app = SimpleNamespace(state=SimpleNamespace(settings=settings, engine_tasks={},
                          runtime=SimpleNamespace(db_manager=db, trading_manager=manager)))
    try:
        yield app
    finally:
        db.engine.dispose()


def test_intentionally_disabled_provider_is_visible_but_does_not_degrade_readiness(application):
    news = application.state.runtime.trading_manager.news_processor
    news._record_status("gdelt", True)
    news._record_status("rss", True)
    assert asyncio.run(news.fetch_marketaux_news(["BTC/USDT"])) == []
    result = health_payload(application)
    assert result["status"] == "ok"
    disabled = result["news_providers"]["marketaux"]
    assert disabled["enabled"] is False and disabled["state"] == "disabled"
    assert disabled["ok"] is False
    assert news.http_client.calls == []
    assert evaluate_news_gate([], result["news_providers"], application.state.settings)["entry_allowed"] is False


def test_selected_provider_without_credential_degrades_readiness(application):
    settings = application.state.settings
    settings.NEWS_ENABLED_KEYED_PROVIDERS = ["marketaux"]
    settings.MARKETAUX_API_KEY = None
    news = application.state.runtime.trading_manager.news_processor
    assert asyncio.run(news.fetch_marketaux_news(["BTC/USDT"])) == []
    result = health_payload(application)
    status = result["news_providers"]["marketaux"]
    assert result["status"] == "degraded"
    assert status["enabled"] is True and status["state"] == "unhealthy"
    assert status["detail"] == "provider_credentials_missing"
    assert news.http_client.calls == []


@pytest.mark.parametrize("status", [
    {"enabled": True, "ok": False, "state": "unhealthy"},
    {"ok": False},  # Legacy statuses remain fail-closed.
])
def test_real_or_legacy_provider_failure_still_degrades_readiness(application, status):
    news = application.state.runtime.trading_manager.news_processor
    news.provider_status["gdelt"] = status
    assert health_payload(application)["status"] == "degraded"


def test_disabled_provider_never_satisfies_entry_gate_even_if_ok_was_inconsistent():
    now = datetime.now(timezone.utc)
    settings = Settings(_env_file=None, NEWS_FAIL_CLOSED_FOR_ENTRY=True,
                        NEWS_MIN_ARTICLES_FOR_ENTRY=1, NEWS_MIN_HEALTHY_PROVIDERS=1)
    result = evaluate_news_gate([{"time_published": now.isoformat(), "sentiment_score": 0}],
                               {"marketaux": {"enabled": False, "ok": True}}, settings, now=now)
    assert result["healthy_providers"] == 0 and result["entry_allowed"] is False


@pytest.mark.parametrize("selected,expected_state", [(False, "disabled"), (True, "unhealthy")])
def test_coingecko_pro_distinguishes_not_selected_from_missing_key(selected, expected_state):
    settings = Settings(_env_file=None, COINGECKO_BASE_URL="https://pro-api.coingecko.com/api/v3",
                        COINGECKO_API_KEY=None, NEWS_ENABLED_KEYED_PROVIDERS=["coingecko"] if selected else [])
    http = FakeAsyncHTTP(lambda *_: {})
    news = NewsProcessor(settings, http_client=http)
    assert asyncio.run(news.fetch_trending(["BTC/USDT"])) == []
    assert news.health()["coingecko"]["state"] == expected_state
    assert news.health()["coingecko"]["ok"] is False and http.calls == []
