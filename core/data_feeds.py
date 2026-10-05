"""Orquestração de dados de mercado para o motor central."""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable

import pandas as pd

from core.feed_quality import FeedQualityError, assess_ohlcv_quality
from core.flow_analysis import analyze_order_flow

logger = logging.getLogger(__name__)


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
    data_quality: Dict[str, Dict[str, Any]] = field(default_factory=dict)

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
            "data_quality": {key: dict(value) for key, value in self.data_quality.items()},
        }


class MultiTimeframeFeed:
    """Busca e normaliza todos os dados que alimentam uma decisão.

    Mercado e histórico são obrigatórios. Notícias, tendências e livro de
    ofertas degradam para listas vazias quando o provedor falha; o chamador
    recebe o erro no snapshot para decidir se o gate deve permanecer fechado.
    """

    def __init__(self, market_connector: Any, news_processor: Any, settings: Any, db_manager: Any | None = None):
        self.market_connector = market_connector
        self.news_processor = news_processor
        self.settings = settings
        self.db_manager = db_manager or getattr(news_processor, "db_manager", None)

    def _source(self) -> str:
        return str(getattr(self.settings, "MARKET_ADAPTER", self.market_connector.__class__.__name__)).lower()

    def _market_type(self) -> str:
        value = str(getattr(self.market_connector, "market", "") or getattr(self.settings, "MARKET_ADAPTER", "crypto")).lower()
        if value in {"binance", "ccxt", "spot", "futures"}:
            return "crypto"
        if value in {"stocks", "stock", "yahoo"}:
            return "b3"
        if value in {"fx"}:
            return "forex"
        return value

    async def _record_incidents(self, symbol: str, timeframe: str, incidents: list[dict[str, Any]]) -> None:
        recorder = getattr(self.db_manager, "record_feed_incidents", None)
        if recorder is None:
            return
        try:
            await asyncio.to_thread(recorder, self._source(), symbol, timeframe, incidents)
        except Exception:
            # Persistência observacional não deve mascarar a avaliação de qualidade.
            logger.exception("Falha ao registrar incidentes do feed %s/%s", symbol, timeframe)

    async def _record_unavailable(self, symbol: str, timeframe: str, kind: str, exc: Exception) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._record_incidents(symbol, timeframe, [{
            "kind": kind,
            "gap_start": now,
            "gap_end": now,
            "details": {"reason": str(exc)[:1000]},
        }])

    def _supports_order_book_history(self) -> bool:
        if not bool(getattr(self.settings, "ORDER_BOOK_HISTORY_ENABLED", True)):
            return False
        adapter = str(getattr(self.settings, "MARKET_ADAPTER", "binance")).lower()
        mode = str(getattr(self.settings, "BINANCE_MODE", "simulated")).lower()
        return adapter == "ccxt" or (adapter == "binance" and mode in {"testnet", "demo"})

    async def _persist_order_book(self, symbol: str, order_book: Dict[str, Any]) -> None:
        persist = getattr(self.db_manager, "persist_order_book_snapshot", None)
        bids = order_book.get("bids") if isinstance(order_book, dict) else None
        asks = order_book.get("asks") if isinstance(order_book, dict) else None
        if persist is None or not self._supports_order_book_history() or not bids or not asks:
            return
        try:
            await asyncio.to_thread(
                persist,
                self._source(),
                symbol,
                order_book,
                datetime.now(timezone.utc),
                int(getattr(self.settings, "ORDER_BOOK_HISTORY_RETENTION_DAYS", 7)),
                int(getattr(self.settings, "ORDER_BOOK_HISTORY_INTERVAL_SECONDS", 60)),
            )
            await self._record_incidents(symbol, "book", [])
        except Exception:
            logger.exception("Falha ao persistir histórico de order book para %s", symbol)

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

    async def _history(self, symbol: str, timeframe: str, limit: int) -> tuple[pd.DataFrame, Dict[str, Any]]:
        frame = await self.market_connector.get_historical_data(symbol, timeframe, limit=limit)
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            error = FeedUnavailable(f"histórico vazio para {timeframe}")
            await self._record_unavailable(symbol, timeframe, "feed_unavailable", error)
            raise error
        volume_missing_rows = 0
        if self._market_type() == "forex":
            frame = frame.copy()
            if "volume" not in frame.columns:
                frame["volume"] = 0.0
                volume_missing_rows = len(frame)
            else:
                original_volume = frame["volume"]
                missing = original_volume.isna()
                volume_missing_rows = int(missing.sum())
                if volume_missing_rows:
                    frame.loc[missing, "volume"] = 0.0
        for column in ("open", "high", "low", "close", "volume"):
            if column in frame.columns:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
        try:
            report = assess_ohlcv_quality(
                frame,
                timeframe=timeframe,
                market=self._market_type(),
                staleness_multiplier=float(getattr(self.settings, "FEED_STALENESS_MULTIPLIER", 3.0)),
            )
        except FeedQualityError as exc:
            await self._record_incidents(symbol, timeframe, exc.incidents)
            raise FeedUnavailable(str(exc)) from exc
        if volume_missing_rows:
            report["volume_missing_rows_filled_zero"] = volume_missing_rows
        await self._record_incidents(symbol, timeframe, list(report.get("incidents", [])))
        return frame, report

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
        data_quality: Dict[str, Dict[str, Any]] = {}
        errors: Dict[str, str] = {}
        for timeframe, result in zip(selected_timeframes, history_results):
            if isinstance(result, Exception):
                errors[f"history:{timeframe}"] = str(result)
                if not isinstance(result, FeedUnavailable):
                    await self._record_unavailable(symbol, timeframe, "feed_unavailable", result)
            else:
                frame, quality_report = result
                historical[timeframe] = frame
                data_quality[timeframe] = quality_report
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
            await self._record_unavailable(
                symbol,
                "quote",
                "market_quote_unavailable",
                market_result if isinstance(market_result, Exception) else FeedUnavailable("resposta de cotação inválida"),
            )
            raise FeedUnavailable(f"cotação indisponível: {market_result}")
        market = market_result
        try:
            quote_price = float(market.get("last"))
        except (TypeError, ValueError):
            quote_price = math.nan
        if not math.isfinite(quote_price) or quote_price <= 0:
            error = FeedUnavailable("cotação com preço ausente, não numérico ou não positivo")
            await self._record_unavailable(symbol, "quote", "market_quote_unavailable", error)
            raise error
        await self._record_incidents(symbol, "quote", [])
        if isinstance(book_result, Exception) or not isinstance(book_result, dict):
            errors["order_book"] = str(book_result)
            order_book: Dict[str, Any] = {}
            await self._record_unavailable(
                symbol,
                "book",
                "order_book_unavailable",
                book_result if isinstance(book_result, Exception) else FeedUnavailable("resposta de order book inválida"),
            )
        else:
            order_book = book_result
            await self._persist_order_book(symbol, order_book)
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
            data_quality=data_quality,
        )
