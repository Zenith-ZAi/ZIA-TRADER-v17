"""Comandos de sincronização e análise do ecossistema de trading."""

from __future__ import annotations

import asyncio
from typing import Any, Iterable

import pandas as pd

from config.settings import Settings
from core.data_feeds import MultiTimeframeFeed
from core.learning_layer import SignalLearningLayer
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
        requested = [str(symbol).strip() for symbol in (symbols or self.settings.SYMBOLS) if str(symbol).strip()]
        if not requested:
            raise ValueError("ao menos um símbolo deve ser informado")
        snapshots = await asyncio.gather(
            *(self._feed(offline).fetch_snapshot(symbol, limit=limit) for symbol in requested),
            return_exceptions=True,
        )
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
