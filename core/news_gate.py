"""Gates determinísticos para disponibilidade e risco de notícias."""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Iterable


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        try:
            result = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                result = parsedate_to_datetime(text)
            except (TypeError, ValueError, IndexError):
                return None
    else:
        return None
    if result.tzinfo is None:
        return result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def evaluate_news_gate(
    articles: Iterable[Dict[str, Any]] | None,
    provider_health: Dict[str, Dict[str, Any]] | None,
    settings: Any,
    now: datetime | None = None,
) -> Dict[str, Any]:
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    article_list = list(articles or [])
    health = provider_health or {}
    healthy_providers = sum(1 for status in health.values() if isinstance(status, dict) and status.get("ok"))
    max_age = max(0, int(getattr(settings, "NEWS_MAX_ARTICLE_AGE_SECONDS", 7200)))
    fresh_articles = 0
    unknown_timestamp_articles = 0
    for article in article_list:
        published = _parse_timestamp(article.get("time_published") or article.get("published_at") or article.get("published"))
        if published is None:
            unknown_timestamp_articles += 1
        elif (now_utc - published).total_seconds() <= max_age:
            fresh_articles += 1
    usable_articles = fresh_articles + unknown_timestamp_articles
    min_providers = max(0, int(getattr(settings, "NEWS_MIN_HEALTHY_PROVIDERS", 1)))
    min_articles = max(0, int(getattr(settings, "NEWS_MIN_ARTICLES_FOR_ENTRY", 1)))
    fail_closed = bool(getattr(settings, "NEWS_FAIL_CLOSED_FOR_ENTRY", True))
    availability_ok = (
        not fail_closed
        or (healthy_providers >= min_providers and usable_articles >= min_articles)
    )
    scores = [float(article.get("sentiment_score", 0.0) or 0.0) for article in article_list]
    sentiment = sum(scores) / len(scores) if scores else 0.0
    shock_threshold = float(getattr(settings, "NEWS_SHOCK_SENTIMENT_THRESHOLD", -0.65))
    shock_min = max(1, int(getattr(settings, "NEWS_SHOCK_MIN_ARTICLES", 3)))
    news_shock = len(article_list) >= shock_min and sentiment <= shock_threshold
    return {
        "entry_allowed": availability_ok,
        "fail_closed": fail_closed,
        "healthy_providers": healthy_providers,
        "required_healthy_providers": min_providers,
        "article_count": len(article_list),
        "fresh_articles": fresh_articles,
        "unknown_timestamp_articles": unknown_timestamp_articles,
        "required_articles": min_articles,
        "average_sentiment": float(sentiment),
        "news_shock": news_shock,
        "reason": "contexto de notícias disponível" if availability_ok else "notícias insuficientes ou provedores indisponíveis",
    }
