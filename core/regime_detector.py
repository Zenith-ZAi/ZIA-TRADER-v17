"""Detector de Regime de Mercado para ajuste dinâmico de IA.
Classifica o mercado em: Tendência Forte, Volátil, Lateral ou Exaustão.
"""

from __future__ import annotations

import math
from typing import Any, Dict

import numpy as np
import pandas as pd

class MarketRegimeDetector:
    """Analisa a microestrutura e indicadores para definir o regime atual."""

    def __init__(self, lookback: int = 20):
        self.lookback = max(1, int(lookback))

    @staticmethod
    def _bad_data(reason: str) -> Dict[str, Any]:
        """Return a finite, stable result for an unusable frame."""
        return {
            "regime": "unknown",
            "status": "bad_data",
            "reason": reason,
            "volatility_index": 0.0,
            "trend_index": 0.0,
            "action_multiplier": 1.0,
        }

    def detect(self, df: pd.DataFrame) -> Dict[str, Any]:
        if not isinstance(df, pd.DataFrame):
            return self._bad_data("dados de regime não são um DataFrame")
        if len(df) < self.lookback:
            return self._bad_data(f"histórico insuficiente: são necessárias {self.lookback} barras")

        required_columns = ("high", "low", "close")
        missing_columns = [column for column in required_columns if column not in df.columns]
        if missing_columns:
            return self._bad_data("colunas OHLC ausentes: " + ", ".join(missing_columns))

        recent = df.loc[:, list(required_columns)].tail(self.lookback).apply(pd.to_numeric, errors="coerce")
        recent = recent.replace([np.inf, -np.inf], np.nan)
        if recent.isna().any().any():
            return self._bad_data("dados OHLC ausentes ou não finitos")

        if (recent <= 0).any().any():
            return self._bad_data("preços OHLC devem ser positivos")
        if (recent["high"] < recent["low"]).any():
            return self._bad_data("high/low invertidos")

        
        # 1. Volatilidade Relativa (ATR normalizado)
        high_low = recent['high'] - recent['low']
        avg_volatility = high_low.mean()
        current_volatility = high_low.iloc[-1]
        vol_ratio = current_volatility / avg_volatility if avg_volatility > 0 else 1.0

        # 2. Força da Tendência (ADX simplificado ou inclinação EMA)
        ema_short = recent['close'].ewm(span=10).mean()
        ema_long = recent['close'].ewm(span=self.lookback).mean()
        trend_diff = (ema_short.iloc[-1] - ema_long.iloc[-1]) / ema_long.iloc[-1]

        if not all(math.isfinite(float(value)) for value in (vol_ratio, trend_diff)):
            return self._bad_data("índices de regime não finitos")
        
        # 3. Classificação
        if vol_ratio > 1.5:
            regime = "high_volatility"
        elif abs(trend_diff) > 0.01:
            regime = "strong_trend"
        elif vol_ratio < 0.7:
            regime = "low_volatility_sideways"
        else:
            regime = "normal"

        return {
            "regime": regime,
            "volatility_index": float(vol_ratio),
            "trend_index": float(trend_diff),
            "action_multiplier": 1.2 if regime == "strong_trend" else 0.8 if regime == "high_volatility" else 1.0
        }
