from __future__ import annotations

import asyncio
import json
import logging

import httpx
import pytest

from config.settings import Settings
from data.news_processor import NewsProcessor
from infra.async_http import AsyncProviderHTTP, ProviderRequestError
from infra.provider_security import ProviderEndpointRejected, validate_news_endpoint
from tests.fakes import FakeAsyncHTTP


@pytest.mark.parametrize("url", [
    "http://api.marketaux.com/v1/news/all",
    "https://api.marketaux.com.evil.test/v1/news/all",
    "https://api.marketaux.com:444/v1/news/all",
    "https://user:secret@api.marketaux.com/v1/news/all",
    "https://127.0.0.1/v1/news/all",
    "https://api.marketaux.com/v1/news/all?api_token=secret",
    "https://api.marketaux.com/v1/news/all#secret",
    "https://api.marketaux.com/not-news",
    "https://api.marketaux.com:invalid/v1/news/all",
])
def test_news_endpoint_policy_rejects_unsafe_destination(url):
    with pytest.raises(ProviderEndpointRejected, match="^provider_endpoint_not_allowlisted$"):
        validate_news_endpoint("marketaux", url)


def test_provider_cache_partitioned_by_headers_and_method_without_raw_secrets():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"response_number": len(calls)})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False) as client:
            transport = AsyncProviderHTTP(client=client, max_retries=0)
            url = "https://www.alphavantage.co/query"
            first = await transport.get_json("test", url, params={"apikey": "query-secret"},
                                             headers={"Authorization": "Bearer header-secret-A"}, ttl_seconds=60)
            repeated = await transport.get_json("test", url, params={"apikey": "query-secret"},
                                                headers={"Authorization": "Bearer header-secret-A"}, ttl_seconds=60)
            other = await transport.get_json("test", url, params={"apikey": "query-secret"},
                                             headers={"Authorization": "Bearer header-secret-B"}, ttl_seconds=60)
            assert first == repeated and first != other and len(calls) == 2
            assert "query-secret" not in repr(transport._cache)
            assert "header-secret" not in repr(transport._cache)
            assert all(len(key) == 64 for key in transport._cache)
            assert transport._cache_key("test", url, {}, "json", method="HEAD") != transport._cache_key("test", url, {}, "json", method="GET")

    asyncio.run(run())


def test_http_errors_health_and_info_logs_do_not_include_secret(caplog):
    secret = "dummy-sensitive-query-value"

    def handler(request):
        return httpx.Response(401, json={"error": secret})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False) as client:
            transport = AsyncProviderHTTP(client=client, max_retries=0)
            with pytest.raises(ProviderRequestError, match="^provider_http_401$") as raised:
                await transport.get_json("alpha_vantage", "https://www.alphavantage.co/query", params={"apikey": secret})
            assert secret not in str(raised.value)
            assert transport.health("alpha_vantage")["alpha_vantage"]["last_error"] == "provider_http_401"
            assert secret not in json.dumps(transport.health())

    with caplog.at_level(logging.INFO, logger="httpx"):
        asyncio.run(run())
    assert secret not in caplog.text
    assert "apikey=" not in caplog.text


def test_default_transport_will_not_follow_credential_redirects():
    async def run():
        transport = AsyncProviderHTTP(max_retries=0)
        try:
            assert transport.client.follow_redirects is False
            assert transport.client._trust_env is False
        finally:
            await transport.aclose()
    asyncio.run(run())


def test_injected_transport_cannot_follow_redirect_to_other_host():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://evil.test/receive"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True, trust_env=False) as client:
            transport = AsyncProviderHTTP(client=client, max_retries=0)
            with pytest.raises(ProviderRequestError, match="^provider_http_302$"):
                await transport.get_json("marketaux", "https://api.marketaux.com/v1/news/all", params={"api_token": "dummy-key"})
        assert len(calls) == 1 and "evil.test" not in calls[0]

    asyncio.run(run())


def test_news_rejects_custom_url_before_sending_credentials():
    settings = Settings(_env_file=None, MARKETAUX_API_KEY="dummy-sensitive-query-value",
                        NEWS_ENABLED_KEYED_PROVIDERS=["marketaux"],
                        MARKETAUX_BASE_URL="https://evil.test/news")
    http = FakeAsyncHTTP(lambda *_: {"data": []})
    processor = NewsProcessor(settings, http_client=http)
    assert asyncio.run(processor.fetch_marketaux_news(["BTC/USDT"])) == []
    assert http.calls == []
    assert processor.health()["marketaux"]["detail"] == "provider_endpoint_not_allowlisted"


def test_news_errors_are_safe_and_do_not_manufacture_articles(caplog):
    secret = "dummy-sensitive-query-value"
    settings = Settings(_env_file=None, MARKETAUX_API_KEY=secret,
                        NEWS_ENABLED_KEYED_PROVIDERS=["marketaux"])

    def failure(*_):
        raise TimeoutError("URL https://api.marketaux.com/v1/news/all?api_token=" + secret)

    http = FakeAsyncHTTP(failure)
    processor = NewsProcessor(settings, http_client=http)
    with caplog.at_level(logging.WARNING):
        assert asyncio.run(processor.fetch_marketaux_news(["BTC/USDT"])) == []
    assert processor.health()["marketaux"]["detail"] == "provider_timeout"
    assert secret not in caplog.text + json.dumps(processor.health())


def test_error_payload_information_is_not_recorded_as_healthy_or_exposed():
    secret = "dummy-sensitive-provider-message"
    settings = Settings(_env_file=None, ALPHA_VANTAGE_API_KEY="dummy-key",
                        NEWS_ENABLED_KEYED_PROVIDERS=["alpha_vantage"])
    processor = NewsProcessor(settings, http_client=FakeAsyncHTTP(lambda *_: {"Information": secret}))
    assert asyncio.run(processor.fetch_alpha_vantage_news(["BTC/USDT"])) == []
    assert processor.health()["alpha_vantage"]["ok"] is False
    assert secret not in json.dumps(processor.health())


def test_loading_key_alone_does_not_opt_into_keyed_news_provider():
    settings = Settings(_env_file=None, MARKETAUX_API_KEY="dummy-key", NEWS_ENABLED_KEYED_PROVIDERS=[])
    http = FakeAsyncHTTP(lambda *_: {"data": []})
    processor = NewsProcessor(settings, http_client=http)
    assert asyncio.run(processor.fetch_marketaux_news(["BTC/USDT"])) == []
    assert http.calls == []
    assert processor.health()["marketaux"]["ok"] is False


def test_cancelled_http_request_preserves_cancellation_and_does_not_open_circuit():
    class CancelledClient:
        async def request(self, *args, **kwargs):
            raise asyncio.CancelledError()

    async def run():
        transport = AsyncProviderHTTP(client=CancelledClient())
        with pytest.raises(asyncio.CancelledError):
            await transport.get_json("cancelled", "https://www.alphavantage.co/query")
        assert transport.health("cancelled")["cancelled"]["failures"] == 0

    asyncio.run(run())


def test_alpha_vantage_news_uses_crypto_and_forex_namespaces():
    settings = Settings(_env_file=None, ALPHA_VANTAGE_API_KEY="dummy-key",
                        NEWS_ENABLED_KEYED_PROVIDERS=["alpha_vantage"])
    http = FakeAsyncHTTP(lambda *_: {"feed": []})
    processor = NewsProcessor(settings, http_client=http)
    asyncio.run(processor.fetch_alpha_vantage_news(["BTC/USDT"]))
    assert http.calls[0]["params"]["tickers"] == "CRYPTO:BTC"
    assert NewsProcessor._alpha_news_symbols(["EUR/USD", "AAPL"]) == ["AAPL", "FOREX:EUR", "FOREX:USD"]


def test_marketaux_request_is_conservatively_limited_to_three_articles():
    settings = Settings(_env_file=None, MARKETAUX_API_KEY="dummy-key", NEWS_PROVIDER_ARTICLES=20,
                        NEWS_ENABLED_KEYED_PROVIDERS=["marketaux"])
    http = FakeAsyncHTTP(lambda *_: {"data": []})
    processor = NewsProcessor(settings, http_client=http)
    asyncio.run(processor.fetch_marketaux_news(["BTC/USDT"]))
    assert http.calls[0]["params"]["limit"] == 3


def test_injected_http_client_with_environment_trust_is_rejected():
    async def run():
        async with httpx.AsyncClient(trust_env=True) as client:
            with pytest.raises(ValueError, match="^http_client_environment_trust_forbidden$"):
                AsyncProviderHTTP(client=client)
    asyncio.run(run())


def test_owned_clients_do_not_inherit_proxy_or_ca_environment(monkeypatch):
    from core.market_data_collector import UnifiedMarketDataCollector
    from scripts.sandbox_backend_smoke import PublicDataSettings
    monkeypatch.setenv("HTTPS_PROXY", "http://untrusted-proxy.invalid:8080")
    monkeypatch.setenv("ALL_PROXY", "http://untrusted-proxy.invalid:8080")
    monkeypatch.setenv("SSL_CERT_FILE", "/nonexistent-untrusted-ca.pem")

    async def run():
        transport = AsyncProviderHTTP(max_retries=0)
        collector = UnifiedMarketDataCollector(PublicDataSettings(), object())
        try:
            assert transport.client._trust_env is False
            assert collector._transport_client._trust_env is False
            assert collector._transport_client.follow_redirects is False
        finally:
            await transport.aclose()
            await collector.aclose()
    asyncio.run(run())


def test_spot_sandbox_client_does_not_inherit_proxy_environment(monkeypatch):
    from execution.binance_adapter import BinanceSpotAdapter
    monkeypatch.setenv("HTTPS_PROXY", "http://untrusted-proxy.invalid:8080")
    monkeypatch.setenv("SSL_CERT_FILE", "/nonexistent-untrusted-ca.pem")
    settings = Settings(_env_file=None, BINANCE_MODE="testnet", BINANCE_BASE_URL="https://testnet.binance.vision/api",
                        BINANCE_API_KEY="dummy-key", BINANCE_SECRET_KEY="dummy-key-secret")
    async def run():
        adapter = BinanceSpotAdapter(settings)
        try:
            assert adapter.http_client._trust_env is False
            assert adapter.http_client.follow_redirects is False
        finally:
            await adapter.close()
    asyncio.run(run())


@pytest.mark.parametrize("base_url,expected_calls", [
    ("https://api.coingecko.com/api/v3", 1),
    ("https://pro-api.coingecko.com/api/v3", 0),
])
def test_coingecko_key_does_not_implicitly_authorize_paid_requests(base_url, expected_calls):
    settings = Settings(_env_file=None, COINGECKO_API_KEY="dummy-key", COINGECKO_BASE_URL=base_url,
                        NEWS_ENABLED_KEYED_PROVIDERS=[])
    http = FakeAsyncHTTP(lambda *_: {"coins": []})
    processor = NewsProcessor(settings, http_client=http)
    assert asyncio.run(processor.fetch_trending(["BTC/USDT"])) == []
    assert len(http.calls) == expected_calls
    if http.calls:
        assert http.calls[0]["headers"] == {}
