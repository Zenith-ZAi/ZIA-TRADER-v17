"""Orquestração de dados de mercado para o motor central."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable

import pandas as pd

from core.flow_analysis import analyze_order_flow


class FeedUnavailable(RuntimeError):
    """Indica que um dado obrigatório não pôde ser obtido."""


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    historical: Dict[str, pd.DataFrame]
    market: Dict[str, Any]
    order_book: Dict[str, Any]
    order_flow: Dict[str, Any]
    news: list[Dict[str, Any]] = field(default_factory=list)
    trends: list[Dict[str, Any]] = field(default_factory=list)
    errors: Dict[str, str] = field(default_factory=dict)
    observed_at: str = ""

    @property
    def primary_history(self) -> pd.DataFrame:
        return next(iter(self.historical.values()), pd.DataFrame())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframes": list(self.historical),
            "market": self.market,
            "order_book": self.order_book,
            "order_flow": self.order_flow,
            "news_count": len(self.news),
            "trend_count": len(self.trends),
            "errors": dict(self.errors),
            "observed_at": self.observed_at,
        }


class MultiTimeframeFeed:
    """Busca e normaliza todos os dados que alimentam uma decisão.

    Mercado e histórico são obrigatórios. Notícias, tendências e livro de
    ofertas degradam para listas vazias quando o provedor falha; o chamador
    recebe o erro no snapshot para decidir se o gate deve permanecer fechado.
    """

    def __init__(self, market_connector: Any, news_processor: Any, settings: Any):
        self.market_connector = market_connector
        self.news_processor = news_processor
        self.settings = settings

    @staticmethod
    def _unique_timeframes(primary: str, configured: str | Iterable[str]) -> list[str]:
        values = [primary]
        if isinstance(configured, str):
            values.extend(configured.split(","))
        else:
            values.extend(configured)
        result: list[str] = []
        for value in values:
            timeframe = str(value).strip()
            if timeframe and timeframe not in result:
                result.append(timeframe)
        return result

    async def _history(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        frame = await self.market_connector.get_historical_data(symbol, timeframe, limit=limit)
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            raise FeedUnavailable(f"histórico vazio para {timeframe}")
        return frame

    async def fetch_snapshot(
        self,
        symbol: str,
        primary_timeframe: str | None = None,
        timeframes: str | Iterable[str] | None = None,
        limit: int = 250,
    ) -> MarketSnapshot:
        primary = primary_timeframe or str(getattr(self.settings, "TIMEFRAME", "1h"))
        configured = timeframes if timeframes is not None else getattr(self.settings, "ANALYSIS_TIMEFRAMES", primary)
        selected_timeframes = self._unique_timeframes(primary, configured)
        safe_limit = max(40, min(int(limit), 2000))
        history_results = await asyncio.gather(
            *(self._history(symbol, timeframe, safe_limit) for timeframe in selected_timeframes),
            return_exceptions=True,
        )
        historical: Dict[str, pd.DataFrame] = {}
        errors: Dict[str, str] = {}
        for timeframe, result in zip(selected_timeframes, history_results):
            if isinstance(result, Exception):
                errors[f"history:{timeframe}"] = str(result)
            else:
                historical[timeframe] = result
        if primary not in historical:
            raise FeedUnavailable(errors.get(f"history:{primary}", "histórico primário indisponível"))

        market_result, book_result, news_result, trend_result = await asyncio.gather(
            self.market_connector.get_market_data(symbol),
            self.market_connector.get_order_book(symbol, limit=20),
            self.news_processor.fetch_all([symbol]),
            self.news_processor.fetch_trending([symbol]),
            return_exceptions=True,
        )
        if isinstance(market_result, Exception) or not isinstance(market_result, dict):
            raise FeedUnavailable(f"cotação indisponível: {market_result}")
        market = market_result
        if isinstance(book_result, Exception) or not isinstance(book_result, dict):
            errors["order_book"] = str(book_result)
            order_book: Dict[str, Any] = {}
        else:
            order_book = book_result
        news = [] if isinstance(news_result, Exception) else list(news_result or [])
        trends = [] if isinstance(trend_result, Exception) else list(trend_result or [])
        if isinstance(news_result, Exception):
            errors["news"] = str(news_result)
        if isinstance(trend_result, Exception):
            errors["trends"] = str(trend_result)
        order_flow = analyze_order_flow(
            order_book,
            ratio_threshold=float(getattr(self.settings, "ORDER_FLOW_RATIO_THRESHOLD", 2.0)),
        )
        return MarketSnapshot(
            symbol=symbol,
            historical=historical,
            market=market,
            order_book=order_book,
            order_flow=order_flow,
            news=news,
            trends=trends,
            errors=errors,
            observed_at=datetime.now(timezone.utc).isoformat(),
        )
