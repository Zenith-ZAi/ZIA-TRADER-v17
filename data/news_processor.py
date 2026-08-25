"""Ingestão híbrida de notícias e tendências com fallback e cache local."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from urllib.parse import quote_plus
from xml.etree import ElementTree
from typing import Any, Dict, Iterable, List, Optional

import requests

from config.settings import Settings

logger = logging.getLogger(__name__)


class NewsProcessor:
    """Busca sinais externos sem fabricar notícias quando um provedor falha."""

    def __init__(self, settings: Settings, db_manager: Any | None = None):
        self.settings = settings
        self.db_manager = db_manager
        self._cache: Dict[str, tuple[float, Any]] = {}
        self.provider_status: Dict[str, Dict[str, Any]] = {}
        logger.info("NewsProcessor inicializado com provedores gratuitos e pagos opcionais.")

    def _cache_get(self, key: str) -> Any | None:
        entry = self._cache.get(key)
        if entry and entry[0] > time.monotonic():
            return entry[1]
        self._cache.pop(key, None)
        return None

    def _cache_set(self, key: str, value: Any) -> Any:
        self._cache[key] = (time.monotonic() + self.settings.NEWS_CACHE_TTL_SECONDS, value)
        return value

    def _record_status(self, provider: str, ok: bool, detail: str = "") -> None:
        self.provider_status[provider] = {
            "ok": ok,
            "detail": detail,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    def _request_json_sync(
        self,
        provider: str,
        url: str,
        params: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        response = requests.get(
            url,
            params=params,
            headers=headers or {},
            timeout=self.settings.NEWS_HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and (payload.get("Error Message") or payload.get("Note") or payload.get("error") or payload.get("status") == "error"):
            raise ValueError(str(payload.get("Error Message") or payload.get("Note") or payload.get("error") or payload.get("message") or "provider error"))
        self._record_status(provider, True)
        return payload

    async def _request_json(
        self,
        provider: str,
        url: str,
        params: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        try:
            return await asyncio.to_thread(self._request_json_sync, provider, url, params, headers)
        except Exception as exc:
            self._record_status(provider, False, str(exc))
            logger.warning("Falha no provedor %s: %s", provider, exc)
            return {}

    def _request_text_sync(self, provider: str, url: str) -> str:
        response = requests.get(url, timeout=self.settings.NEWS_HTTP_TIMEOUT_SECONDS)
        response.raise_for_status()
        self._record_status(provider, True)
        return response.text

    async def _request_text(self, provider: str, url: str) -> str:
        try:
            return await asyncio.to_thread(self._request_text_sync, provider, url)
        except Exception as exc:
            self._record_status(provider, False, str(exc))
            logger.warning("Falha no provedor %s: %s", provider, exc)
            return ""

    @staticmethod
    def _symbols(tickers: Iterable[str]) -> List[str]:
        return sorted({str(ticker).strip().upper() for ticker in tickers if str(ticker).strip()})

    @staticmethod
    def _base_symbols(tickers: Iterable[str]) -> List[str]:
        return sorted({str(ticker).split("/")[0].strip().upper() for ticker in tickers if str(ticker).strip()})

    @staticmethod
    def _normalize(
        source: str,
        title: str,
        summary: str = "",
        url: str = "",
        published_at: str = "",
        score: float = 0.0,
        ticker: str = "",
        **extra: Any,
    ) -> Dict[str, Any]:
        return {
            "source": source,
            "provider": source,
            "title": (title or "").strip(),
            "summary": (summary or "").strip(),
            "url": url or "",
            "time_published": published_at or "",
            "sentiment_score": max(-1.0, min(1.0, float(score or 0.0))),
            "ticker": ticker,
            **extra,
        }

    async def fetch_rss_news(self, tickers: List[str]) -> List[Dict[str, Any]]:
        symbols = self._base_symbols(tickers)
        if not symbols:
            return []
        cache_key = f"rss:{','.join(symbols)}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        query = quote_plus(" OR ".join(symbols))
        url = self.settings.NEWS_RSS_URL_TEMPLATE.format(query=query)
        text = await self._request_text("rss", url)
        if not text:
            return []
        try:
            root = ElementTree.fromstring(text)
        except ElementTree.ParseError as exc:
            self._record_status("rss", False, str(exc))
            return []
        articles = []
        for item in root.findall(".//item")[: self.settings.NEWS_MAX_ARTICLES]:
            articles.append(
                self._normalize(
                    "RSS",
                    item.findtext("title", default=""),
                    item.findtext("description", default=""),
                    item.findtext("link", default=""),
                    item.findtext("pubDate", default=""),
                    0.0,
                )
            )
        return self._cache_set(cache_key, articles)

    async def fetch_gdelt_news(self, tickers: List[str]) -> List[Dict[str, Any]]:
        symbols = self._base_symbols(tickers)
        if not symbols:
            return []
        cache_key = f"gdelt:{','.join(symbols)}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        query = " OR ".join(f'"{symbol}"' for symbol in symbols)
        payload = await self._request_json(
            "gdelt",
            self.settings.GDELT_BASE_URL,
            {
                "query": query,
                "mode": "artlist",
                "format": "json",
                "maxrecords": min(self.settings.NEWS_MAX_ARTICLES, 250),
                "sort": "HybridRel",
                "timespan": "24h",
            },
        )
        articles = []
        for article in payload.get("articles", []) if payload else []:
            articles.append(
                self._normalize(
                    "GDELT",
                    article.get("title", ""),
                    article.get("seendate", ""),
                    article.get("url", ""),
                    article.get("seendate", ""),
                    0.0,
                    domain=article.get("domain", ""),
                    language=article.get("language", ""),
                )
            )
        return self._cache_set(cache_key, articles)

    async def fetch_benzinga_trends(self, tickers: List[str]) -> List[Dict[str, Any]]:
        if not self.settings.BENZINGA_API_KEY:
            return []
        symbols = self._base_symbols(tickers)
        cache_key = f"benzinga-trends:{','.join(symbols)}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        payload = await self._request_json(
            "benzinga_trends",
            self.settings.BENZINGA_TRENDS_URL,
            {
                "token": self.settings.BENZINGA_API_KEY,
                "interval": "1h",
                "tickers": ",".join(symbols),
                "source": "all",
                "pagesize": len(symbols),
            },
        )
        trends = []
        for item in (payload.get("data", []) if payload else []):
            metrics = item.get("metrics", []) or []
            latest = metrics[-1] if metrics else {}
            raw_score = latest.get("scaled_count_mavg", latest.get("scaled_count", 0.0)) or 0.0
            trends.append({
                "source": "Benzinga",
                "provider": "Benzinga",
                "symbol": str(item.get("ticker", "")).upper(),
                "trend_score": max(0.0, min(1.0, float(raw_score))),
                "trend_activity": latest.get("count"),
                "market_count_average": latest.get("market_count_average"),
            })
        return self._cache_set(cache_key, trends)

    async def fetch_trending(self, tickers: List[str]) -> List[Dict[str, Any]]:
        """Busca tendências CoinGecko; ausência de chave usa o endpoint público."""
        cache_key = f"coingecko:trending:{','.join(self._base_symbols(tickers))}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        headers = {}
        if self.settings.COINGECKO_API_KEY:
            headers["x-cg-pro-api-key"] = self.settings.COINGECKO_API_KEY
        payload = await self._request_json(
            "coingecko",
            f"{self.settings.COINGECKO_BASE_URL.rstrip('/')}/search/trending",
            {},
            headers,
        )
        wanted = set(self._base_symbols(tickers))
        trends = []
        for rank, item in enumerate(payload.get("coins", []) if payload else []):
            coin = item.get("item", {})
            symbol = str(coin.get("symbol", "")).upper()
            if wanted and symbol not in wanted:
                continue
            rank_score = max(0.0, 1.0 - (rank / max(len(payload.get("coins", [])), 1)))
            trends.append({
                "source": "CoinGecko",
                "provider": "CoinGecko",
                "symbol": symbol,
                "name": coin.get("name", ""),
                "trend_score": rank_score,
                "market_cap_rank": coin.get("market_cap_rank"),
                "price_change_24h": (coin.get("data") or {}).get("price_change_percentage_24h", {}).get("usd"),
            })
        paid_trends = await self.fetch_benzinga_trends(tickers)
        trends = paid_trends + trends
        if self.db_manager:
            for trend in trends:
                try:
                    self.db_manager.create_trend_snapshot(trend)
                except Exception as exc:
                    logger.warning("Não foi possível persistir tendência: %s", exc)
        return self._cache_set(cache_key, trends)

    async def fetch_marketaux_news(self, tickers: List[str]) -> List[Dict[str, Any]]:
        if not self.settings.MARKETAUX_API_KEY:
            return []
        symbols = self._base_symbols(tickers)
        if not symbols:
            return []
        cache_key = f"marketaux:{','.join(symbols)}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        payload = await self._request_json(
            "marketaux",
            self.settings.MARKETAUX_BASE_URL,
            {
                "api_token": self.settings.MARKETAUX_API_KEY,
                "symbols": ",".join(symbols),
                "filter_entities": "true",
                "must_have_entities": "true",
                "group_similar": "true",
                "language": "en",
                "limit": min(self.settings.NEWS_PROVIDER_ARTICLES, self.settings.NEWS_MAX_ARTICLES),
            },
        )
        articles = []
        wanted = set(symbols)
        for item in (payload.get("data", []) if payload else []):
            entities = item.get("entities") or []
            matching = [entity for entity in entities if str(entity.get("symbol", "")).upper() in wanted]
            scores = [float(entity.get("sentiment_score", 0.0) or 0.0) for entity in matching]
            articles.append(
                self._normalize(
                    "Marketaux",
                    item.get("title", ""),
                    item.get("description", "") or item.get("snippet", ""),
                    item.get("url", ""),
                    item.get("published_at", ""),
                    sum(scores) / len(scores) if scores else 0.0,
                    ticker=next((str(entity.get("symbol", "")).upper() for entity in matching), ""),
                    external_id=item.get("uuid", ""),
                    source_name=item.get("source", ""),
                    relevance_score=item.get("relevance_score"),
                    entities=matching,
                )
            )
        return self._cache_set(cache_key, articles)

    async def fetch_finnhub_news(self, tickers: List[str]) -> List[Dict[str, Any]]:
        if not self.settings.FINNHUB_API_KEY:
            return []
        symbols = self._base_symbols(tickers)
        if not symbols:
            return []
        cache_key = f"finnhub:{self.settings.FINNHUB_NEWS_CATEGORY}:{','.join(symbols)}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        payload = await self._request_json(
            "finnhub",
            f"{self.settings.FINNHUB_BASE_URL.rstrip('/')}/news",
            {
                "category": self.settings.FINNHUB_NEWS_CATEGORY,
                "token": self.settings.FINNHUB_API_KEY,
            },
        )
        wanted = set(symbols)
        articles = []
        for item in (payload if isinstance(payload, list) else []):
            related = {part.strip().upper() for part in str(item.get("related", "")).split(",") if part.strip()}
            if related and not (related & wanted) and self.settings.FINNHUB_NEWS_CATEGORY != "crypto":
                continue
            published = item.get("datetime")
            if isinstance(published, (int, float)):
                published = datetime.fromtimestamp(published, tz=timezone.utc).isoformat()
            articles.append(
                self._normalize(
                    "Finnhub",
                    item.get("headline", ""),
                    item.get("summary", ""),
                    item.get("url", ""),
                    str(published or ""),
                    0.0,
                    ticker=next(iter(related & wanted), ""),
                    external_id=item.get("id", ""),
                    source_name=item.get("source", ""),
                    category=item.get("category", ""),
                )
            )
        return self._cache_set(cache_key, articles[: self.settings.NEWS_PROVIDER_ARTICLES])

    async def fetch_twelve_data_news(self, tickers: List[str]) -> List[Dict[str, Any]]:
        if not self.settings.TWELVE_DATA_API_KEY:
            return []
        symbols = self._symbols(tickers)
        if not symbols:
            return []
        cache_key = f"twelve_data:{','.join(symbols)}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        payload = await self._request_json(
            "twelve_data",
            f"{self.settings.TWELVE_DATA_BASE_URL.rstrip('/')}/news",
            {
                "symbol": ",".join(symbols),
                "apikey": self.settings.TWELVE_DATA_API_KEY,
                "outputsize": min(self.settings.NEWS_PROVIDER_ARTICLES, self.settings.NEWS_MAX_ARTICLES),
                "order": "desc",
            },
        )
        raw_articles = payload.get("values", payload.get("data", [])) if payload else []
        articles = []
        for item in raw_articles if isinstance(raw_articles, list) else []:
            articles.append(
                self._normalize(
                    "TwelveData",
                    item.get("title", item.get("headline", "")),
                    item.get("summary", item.get("description", "")),
                    item.get("url", ""),
                    item.get("published_at", item.get("datetime", "")),
                    item.get("sentiment_score", 0.0),
                    ticker=str(item.get("symbol", symbols[0])).upper(),
                    external_id=item.get("id", ""),
                    source_name=item.get("source", ""),
                )
            )
        return self._cache_set(cache_key, articles)

    async def fetch_alpha_vantage_news(self, tickers: List[str]) -> List[Dict[str, Any]]:
        if not self.settings.ALPHA_VANTAGE_API_KEY:
            return []
        symbols = self._symbols(tickers)
        cache_key = f"alpha:{','.join(symbols)}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        payload = await self._request_json(
            "alpha_vantage",
            "https://www.alphavantage.co/query",
            {
                "function": "NEWS_SENTIMENT",
                "tickers": ",".join(self._base_symbols(symbols)),
                "limit": min(self.settings.NEWS_MAX_ARTICLES, 1000),
                "apikey": self.settings.ALPHA_VANTAGE_API_KEY,
            },
        )
        articles = [
            self._normalize(
                "AlphaVantage",
                item.get("title", ""),
                item.get("summary", ""),
                item.get("url", ""),
                item.get("time_published", ""),
                item.get("overall_sentiment_score", 0.0),
                extra={"sentiment_label": item.get("overall_sentiment_label", "")},
            )
            for item in (payload.get("feed", []) if payload else [])
        ]
        return self._cache_set(cache_key, articles)

    async def fetch_benzinga_news(self, symbols: List[str]) -> List[Dict[str, Any]]:
        if not self.settings.BENZINGA_API_KEY:
            return []
        normalized = self._symbols(symbols)
        cache_key = f"benzinga:{','.join(normalized)}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        payload = await self._request_json(
            "benzinga",
            self.settings.BENZINGA_NEWS_URL,
            {
                "token": self.settings.BENZINGA_API_KEY,
                "tickers": ",".join(normalized),
                "pageSize": min(self.settings.NEWS_MAX_ARTICLES, 100),
            },
        )
        raw_articles = payload.get("data", payload.get("news", [])) if payload else []
        articles = [
            self._normalize(
                "Benzinga",
                item.get("title", item.get("headline", "")),
                item.get("body", item.get("summary", "")),
                item.get("url", ""),
                item.get("created", item.get("updated", "")),
                0.0,
            )
            for item in raw_articles
        ]
        return self._cache_set(cache_key, articles)

    async def fetch_newsapi_news(self, tickers: List[str]) -> List[Dict[str, Any]]:
        if not self.settings.NEWSAPI_API_KEY:
            return []
        query = " OR ".join(self._base_symbols(tickers))
        cache_key = f"newsapi:{query}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        payload = await self._request_json(
            "newsapi",
            self.settings.NEWSAPI_BASE_URL,
            {
                "q": query,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": min(self.settings.NEWS_MAX_ARTICLES, 100),
                "apiKey": self.settings.NEWSAPI_API_KEY,
            },
        )
        articles = [
            self._normalize(
                "NewsAPI",
                item.get("title", ""),
                item.get("description", "") or item.get("content", ""),
                item.get("url", ""),
                item.get("publishedAt", ""),
                0.0,
            )
            for item in (payload.get("articles", []) if payload else [])
        ]
        return self._cache_set(cache_key, articles)

    async def fetch_cryptopanic_news(self, tickers: List[str]) -> List[Dict[str, Any]]:
        if not self.settings.CRYPTOPANIC_API_KEY:
            return []
        cache_key = f"cryptopanic:{','.join(self._base_symbols(tickers))}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        payload = await self._request_json(
            "cryptopanic",
            self.settings.CRYPTOPANIC_BASE_URL,
            {
                "auth_token": self.settings.CRYPTOPANIC_API_KEY,
                "currencies": ",".join(self._base_symbols(tickers)),
                "kind": "news",
            },
        )
        articles = []
        for item in (payload.get("results", []) if payload else []):
            source = item.get("source") or {}
            articles.append(
                self._normalize(
                    "CryptoPanic",
                    item.get("title", ""),
                    "",
                    item.get("url", ""),
                    item.get("published_at", ""),
                    0.0,
                    extra={"source_name": source.get("title", "") if isinstance(source, dict) else str(source)},
                )
            )
        return self._cache_set(cache_key, articles)

    async def fetch_all(self, tickers: List[str]) -> List[Dict[str, Any]]:
        """Consulta fonte gratuita e fontes pagas habilitadas, sem duplicar títulos."""
        provider_calls = [
            ("gdelt", self.fetch_gdelt_news(tickers)),
            ("rss", self.fetch_rss_news(tickers)),
            ("alpha_vantage", self.fetch_alpha_vantage_news(tickers)),
            ("marketaux", self.fetch_marketaux_news(tickers)),
            ("finnhub", self.fetch_finnhub_news(tickers)),
            ("twelve_data", self.fetch_twelve_data_news(tickers)),
            ("benzinga", self.fetch_benzinga_news(tickers)),
            ("newsapi", self.fetch_newsapi_news(tickers)),
            ("cryptopanic", self.fetch_cryptopanic_news(tickers)),
        ]
        results = await asyncio.gather(*(call for _, call in provider_calls), return_exceptions=True)
        buckets: Dict[str, List[Dict[str, Any]]] = {name: [] for name, _ in provider_calls}
        seen = set()
        for (provider, _), result in zip(provider_calls, results):
            if isinstance(result, Exception):
                continue
            for article in result if isinstance(result, list) else []:
                key = article.get("url") or article.get("external_id") or article.get("title")
                if key and key not in seen:
                    seen.add(key)
                    buckets[provider].append(article)
        articles: List[Dict[str, Any]] = []
        while len(articles) < self.settings.NEWS_MAX_ARTICLES and any(buckets.values()):
            for provider, _ in provider_calls:
                if buckets[provider] and len(articles) < self.settings.NEWS_MAX_ARTICLES:
                    articles.append(buckets[provider].pop(0))
        processed = await self.process_news_sentiment(articles)
        if self.db_manager:
            for article in processed:
                try:
                    self.db_manager.create_news_article(article)
                except Exception as exc:
                    logger.warning("Não foi possível persistir notícia: %s", exc)
        return processed

    async def process_news_sentiment(self, news_articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        positive = {"beat", "growth", "surge", "bullish", "positive", "optimistic", "alta", "crescimento", "otimista"}
        negative = {"miss", "drop", "fall", "bearish", "negative", "pessimistic", "queda", "negativa", "pessimista"}
        processed = []
        for article in news_articles:
            copy = dict(article)
            text = f"{copy.get('title', '')} {copy.get('summary', '')}".lower()
            positive_hits = sum(token in text for token in positive)
            negative_hits = sum(token in text for token in negative)
            lexicon_score = (positive_hits - negative_hits) / max(positive_hits + negative_hits, 1)
            provider_score = float(copy.get("sentiment_score", 0.0) or 0.0)
            score = provider_score if provider_score != 0 else lexicon_score
            copy["sentiment_score"] = max(-1.0, min(1.0, score))
            processed.append(copy)
        return processed

    @staticmethod
    def aggregate_sentiment(news_articles: List[Dict[str, Any]]) -> float:
        scores = [float(article.get("sentiment_score", 0.0)) for article in news_articles]
        return max(-1.0, min(1.0, sum(scores) / len(scores))) if scores else 0.0

    @staticmethod
    def aggregate_trend_score(trends: List[Dict[str, Any]]) -> float:
        """Converte somente variação direcional em score; popularidade isolada é neutra."""
        directional = []
        for trend in trends:
            value = trend.get("price_change_24h")
            if value is None:
                continue
            try:
                directional.append(max(-1.0, min(1.0, float(value) / 10.0)))
            except (TypeError, ValueError):
                continue
        return max(-1.0, min(1.0, sum(directional) / len(directional))) if directional else 0.0

    def health(self) -> Dict[str, Dict[str, Any]]:
        return dict(self.provider_status)

    async def close(self) -> None:
        self._cache.clear()
        logger.info("NewsProcessor fechado.")
