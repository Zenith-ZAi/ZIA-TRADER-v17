"""Outbound news-provider policy and public-safe diagnostics; never a secret store."""
from __future__ import annotations

from urllib.parse import urlsplit

import httpx


# Provider identifiers are internal constants, not request-body values.
NEWS_ENDPOINTS = {
    "rss": {("news.google.com", "/rss/search")},
    "gdelt": {("api.gdeltproject.org", "/api/v2/doc/doc")},
    "alpha_vantage": {("www.alphavantage.co", "/query")},
    "marketaux": {("api.marketaux.com", "/v1/news/all")},
    "finnhub": {("finnhub.io", "/api/v1/news")},
    "twelve_data": {("api.twelvedata.com", "/news")},
    "benzinga": {("api.benzinga.com", "/api/v2/news")},
    "benzinga_trends": {("api.benzinga.com", "/api/v1/trending-tickers")},
    "newsapi": {("newsapi.org", "/v2/everything")},
    "cryptopanic": {("cryptopanic.com", "/api/GROWTH/v2/posts/")},
    "coingecko": {
        ("api.coingecko.com", "/api/v3/search/trending"),
        ("pro-api.coingecko.com", "/api/v3/search/trending"),
    },
}


class ProviderEndpointRejected(ValueError):
    def __init__(self) -> None:
        super().__init__("provider_endpoint_not_allowlisted")


def validate_news_endpoint(provider: str, url: str) -> None:
    """Validate before credentials reach the HTTP client; no proxy override bypass."""
    try:
        parsed = urlsplit(url)
        accepted = (
            parsed.scheme == "https"
            and parsed.port in (None, 443)
            and not parsed.username
            and not parsed.password
            and not parsed.fragment
            and (parsed.hostname, parsed.path) in NEWS_ENDPOINTS.get(provider, set())
            # RSS search embeds a public query in its URL; other providers use params.
            and (not parsed.query or provider == "rss")
        )
    except (ValueError, TypeError):
        accepted = False
    if not accepted:
        raise ProviderEndpointRejected()


def safe_provider_error(exc: Exception) -> str:
    """Do not stringify exceptions: URLs, DB params and provider text can contain keys."""
    if isinstance(exc, ProviderEndpointRejected):
        return "provider_endpoint_not_allowlisted"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"provider_http_{exc.response.status_code}"
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return "provider_timeout"
    if isinstance(exc, httpx.TransportError):
        return "provider_transport_error"
    if isinstance(exc, ValueError):
        return "provider_invalid_response"
    return "provider_unavailable"
