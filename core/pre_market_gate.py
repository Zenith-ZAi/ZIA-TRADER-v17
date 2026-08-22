"""Gate pré-mercado determinístico para bloquear entradas sem contexto suficiente."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

import numpy as np
import pandas as pd

from core.news_gate import evaluate_news_gate


class PreMarketGate:
    def __init__(self, settings: Any):
        self.settings = settings

    def evaluate(self, historical_data: pd.DataFrame, news_context: Dict[str, Any] | None = None, market_open: bool = True) -> Dict[str, Any]:
        reasons: list[str] = []
        if not market_open:
            reasons.append("mercado fechado")
        if historical_data is None or not isinstance(historical_data, pd.DataFrame) or len(historical_data) < 40:
            reasons.append("histórico insuficiente para análise pré-mercado")
            return {"allowed": False, "reasons": reasons, "status": "rejected", "timestamp": datetime.now(timezone.utc).isoformat()}
        closes = pd.to_numeric(historical_data.get("close"), errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        if len(closes) < 40 or float(closes.iloc[-1]) <= 0:
            reasons.append("preços inválidos ou insuficientes")
        returns = closes.pct_change().dropna()
        volatility = float(returns.tail(20).std(ddof=0)) if len(returns) >= 20 else float("inf")
        max_volatility = float(getattr(self.settings, "BACKTEST_MAX_VOLATILITY", 0.08))
        if volatility > max_volatility:
            reasons.append(f"volatilidade pré-mercado acima do limite: {volatility:.6f}")
        if isinstance(news_context, dict):
            articles = news_context.get("articles", [])
            provider_health = news_context.get("provider_health", news_context.get("health", {}))
        else:
            articles = news_context or []
            provider_health = {}
        news_gate = evaluate_news_gate(articles, provider_health, self.settings)
        if not news_gate.get("entry_allowed", True):
            reasons.extend(news_gate.get("reasons", ["notícias sem contexto confiável"]))
        return {
            "allowed": not reasons,
            "status": "approved" if not reasons else "rejected",
            "reasons": reasons,
            "volatility": volatility,
            "news_gate": news_gate,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
