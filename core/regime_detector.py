"""Detector de Regime de Mercado para ajuste dinâmico de IA.
Classifica o mercado em: Tendência Forte, Volátil, Lateral ou Exaustão.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Dict, Any

class MarketRegimeDetector:
    """Analisa a microestrutura e indicadores para definir o regime atual."""

    def __init__(self, lookback: int = 20):
        self.lookback = lookback

    def detect(self, df: pd.DataFrame) -> Dict[str, Any]:
        if len(df) < self.lookback:
            return {"regime": "unknown", "volatility": 0.0, "trend_strength": 0.0}

        recent = df.tail(self.lookback)
        
        # 1. Volatilidade Relativa (ATR normalizado)
        high_low = recent['high'] - recent['low']
        avg_volatility = high_low.mean()
        current_volatility = high_low.iloc[-1]
        vol_ratio = current_volatility / avg_volatility if avg_volatility > 0 else 1.0

        # 2. Força da Tendência (ADX simplificado ou inclinação EMA)
        ema_short = recent['close'].ewm(span=10).mean()
        ema_long = recent['close'].ewm(span=self.lookback).mean()
        trend_diff = (ema_short.iloc[-1] - ema_long.iloc[-1]) / ema_long.iloc[-1]
        
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
