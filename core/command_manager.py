"""Comandos de sincronização e análise do ecossistema de trading."""

from __future__ import annotations

import asyncio
from typing import Any, Iterable

import pandas as pd

from config.settings import Settings
from core.data_feeds import MultiTimeframeFeed
from core.learning_layer import SignalLearningLayer
from core.market_data_collector import UnifiedMarketDataCollector
from core.market_signals import calculate_market_signal


class _OfflineNews:
    async def fetch_all(self, tickers: list[str]) -> list[dict[str, Any]]:
        return []

    async def fetch_trending(self, tickers: list[str]) -> list[dict[str, Any]]:
        return []

    @staticmethod
    def aggregate_sentiment(articles: list[dict[str, Any]]) -> float:
        return 0.0

    @staticmethod
    def health() -> dict[str, Any]:
        return {"offline": {"ok": True, "detail": "provedores externos desabilitados no comando offline"}}


class CoreCommandManager:
    """Fachada de comandos para CLI/API e automação supervisionada."""

    MAX_SYNC_SYMBOLS = 20
    MAX_SYNC_CONCURRENCY = 5
    MAX_SYNC_CANDLES = 1000

    def __init__(self, settings: Settings, db_manager: Any, market_connector: Any, news_processor: Any):
        self.settings = settings
        self.db_manager = db_manager
        self.market_connector = market_connector
        self.news_processor = news_processor
        self.data_feed = MultiTimeframeFeed(market_connector, news_processor, settings)
        self.learning = SignalLearningLayer(db_manager, settings)

    def _feed(self, offline: bool = False) -> MultiTimeframeFeed:
        if not offline:
            return self.data_feed
        return MultiTimeframeFeed(self.market_connector, _OfflineNews(), self.settings)

    async def sync_market(
        self,
        symbols: Iterable[str] | None = None,
        limit: int = 250,
        offline: bool = False,
    ) -> dict[str, Any]:
        raw_symbols = self.settings.SYMBOLS if symbols is None else symbols
        if isinstance(raw_symbols, str):
            raw_symbols = [raw_symbols]
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= self.MAX_SYNC_CANDLES:
            raise ValueError(f"limit deve estar entre 1 e {self.MAX_SYNC_CANDLES}")
        requested = []
        seen = set()
        for raw_symbol in raw_symbols:
            if len(requested) >= self.MAX_SYNC_SYMBOLS:
                raise ValueError(f"no máximo {self.MAX_SYNC_SYMBOLS} símbolos por sincronização")
            if not isinstance(raw_symbol, str):
                raise ValueError("cada símbolo deve ser texto")
            symbol = raw_symbol.strip()
            if not symbol or len(symbol) > 64:
                raise ValueError("símbolos não podem ser vazios nem exceder 64 caracteres")
            key = symbol.casefold()
            if key in seen:
                raise ValueError("símbolos duplicados não são permitidos")
            seen.add(key)
            requested.append(symbol)
        if not requested:
            raise ValueError("ao menos um símbolo deve ser informado")
        feed = self._feed(offline)
        semaphore = asyncio.Semaphore(min(self.MAX_SYNC_CONCURRENCY, len(requested)))

        async def fetch_snapshot(symbol: str):
            try:
                async with semaphore:
                    return await feed.fetch_snapshot(symbol, limit=limit)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                return exc

        snapshots = await asyncio.gather(*(fetch_snapshot(symbol) for symbol in requested))
        result: dict[str, Any] = {"symbols": requested, "offline": offline, "snapshots": [], "errors": {}}
        for symbol, snapshot in zip(requested, snapshots):
            if isinstance(snapshot, Exception):
                result["errors"][symbol] = str(snapshot)
            else:
                result["snapshots"].append(snapshot)
        return {
            **{key: value for key, value in result.items() if key != "snapshots"},
            "snapshots": [snapshot.to_dict() for snapshot in result["snapshots"]],
            "successful": len(result["snapshots"]),
        }

    async def collect_market_data(self, **request: Any) -> dict[str, Any]:
        """Collect and optionally persist vendor candles outside the trading feed."""
        collector = UnifiedMarketDataCollector(self.settings, self.db_manager)
        try:
            return await collector.collect(**request)
        finally:
            await collector.aclose()

    async def analyze_symbol(
        self,
        symbol: str,
        limit: int = 250,
        offline: bool = False,
    ) -> dict[str, Any]:
        feed = self._feed(offline)
        snapshot = await feed.fetch_snapshot(symbol, limit=limit)
        news_sentiment = feed.news_processor.aggregate_sentiment(snapshot.news)
        trend_score = self.news_processor.aggregate_trend_score(snapshot.trends) if hasattr(self.news_processor, "aggregate_trend_score") else 0.0
        signal = calculate_market_signal(
            snapshot.primary_history,
            news_sentiment=news_sentiment,
            trend_score=trend_score,
            min_confidence=float(self.settings.MIN_CONFIDENCE_THRESHOLD),
            max_volatility=float(self.settings.BACKTEST_MAX_VOLATILITY),
            order_flow=snapshot.order_book,
            flow_ratio_threshold=float(self.settings.ORDER_FLOW_RATIO_THRESHOLD),
            require_flow_confirmation=bool(self.settings.ORDER_FLOW_CONFIRMATION_REQUIRED),
        )
        return {
            "symbol": symbol,
            "snapshot": snapshot.to_dict(),
            "signal": signal.to_dict(),
            "entry_allowed": bool(signal.action in {"buy", "sell"} and signal.status == "good"),
            "orders_sent": 0,
            "explanation": signal.reasons,
        }

    def label_learning_dataset(
        self,
        frame: pd.DataFrame,
        symbol: str | None = None,
        horizon_bars: int | None = None,
        limit: int = 10000,
    ) -> dict[str, Any]:
        return self.learning.label_observations(frame, symbol, horizon_bars, limit)
