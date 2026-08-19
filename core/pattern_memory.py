from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Any, Dict, Iterable, Optional

import numpy as np
import pandas as pd


PATTERN_FEATURES = (
    "rsi",
    "atr_pct",
    "momentum_5",
    "volume_ratio",
    "news_sentiment",
    "trend_score",
    "pullback_confidence",
    "exhaustion",
    "trigger",
    "direction",
)


@dataclass(frozen=True)
class PatternMatch:
    matched: bool
    distance: float
    outcome_atr: float
    sample_size: int
    pattern_id: Optional[int] = None
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "matched": self.matched,
            "distance": float(self.distance),
            "outcome_atr": float(self.outcome_atr),
            "sample_size": int(self.sample_size),
            "pattern_id": self.pattern_id,
            "reason": self.reason,
        }


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return parsed if np.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def build_pattern_signature(
    historical_data: pd.DataFrame,
    market_signal: Any,
    news_sentiment: float = 0.0,
    trend_score: float = 0.0,
) -> Dict[str, float]:
    """Cria uma assinatura causal compacta do último candle disponível."""
    close = pd.to_numeric(historical_data.get("close"), errors="coerce") if isinstance(historical_data, pd.DataFrame) else pd.Series(dtype=float)
    volume = pd.to_numeric(historical_data.get("volume"), errors="coerce") if isinstance(historical_data, pd.DataFrame) else pd.Series(dtype=float)
    close = close.dropna() if close is not None else pd.Series(dtype=float)
    volume = volume.dropna() if volume is not None else pd.Series(dtype=float)
    last_close = _finite(close.iloc[-1]) if len(close) else 0.0
    momentum_5 = _finite(close.pct_change().tail(5).sum()) if len(close) >= 6 else 0.0
    average_volume = _finite(volume.tail(20).mean()) if len(volume) >= 20 else 0.0
    volume_ratio = _finite(volume.iloc[-1] / average_volume) if average_volume > 0 and len(volume) else 0.0
    indicators = getattr(market_signal, "indicators", {}) or {}
    pullback = getattr(market_signal, "pullback", {}) or {}
    action = str(getattr(market_signal, "action", "hold"))
    direction = 1.0 if action == "buy" else -1.0 if action == "sell" else 0.0
    return {
        "rsi": _finite(indicators.get("rsi"), 50.0),
        "atr_pct": _finite(indicators.get("atr_pct")),
        "momentum_5": momentum_5,
        "volume_ratio": volume_ratio,
        "news_sentiment": _finite(news_sentiment),
        "trend_score": _finite(trend_score),
        "pullback_confidence": _finite(pullback.get("confidence")),
        "exhaustion": 1.0 if pullback.get("exhaustion") else 0.0,
        "trigger": 1.0 if pullback.get("trigger") else 0.0,
        "direction": direction,
    }


class PatternMemory:
    """Memória histórica determinística; não cria dados e não autoriza por si só."""

    def __init__(self, db_manager, settings):
        self.db_manager = db_manager
        self.enabled = bool(getattr(settings, "PATTERN_MEMORY_ENABLED", False))
        self.require_profitable = bool(getattr(settings, "PATTERN_MEMORY_REQUIRE_PROFITABLE", True))
        self.min_outcome_atr = float(getattr(settings, "PATTERN_MEMORY_MIN_OUTCOME_ATR", 2.0))
        self.max_distance = float(getattr(settings, "PATTERN_MEMORY_MAX_DISTANCE", 1.25))
        self.min_samples = max(1, int(getattr(settings, "PATTERN_MEMORY_MIN_SAMPLES", 3)))

    @staticmethod
    def _distance(current: Dict[str, float], historical: Dict[str, Any]) -> float:
        scales = {
            "rsi": 25.0,
            "atr_pct": 0.02,
            "momentum_5": 0.02,
            "volume_ratio": 2.0,
            "news_sentiment": 1.0,
            "trend_score": 1.0,
            "pullback_confidence": 1.0,
            "exhaustion": 1.0,
            "trigger": 1.0,
            "direction": 1.0,
        }
        total = 0.0
        for name in PATTERN_FEATURES:
            left = _finite(current.get(name))
            right = _finite((historical or {}).get(name))
            scale = max(scales.get(name, 1.0), 1e-9)
            total += ((left - right) / scale) ** 2
        return sqrt(total / len(PATTERN_FEATURES))

    def find_match(self, symbol: str, signature: Dict[str, float], strategy: str = "pullback") -> PatternMatch:
        if not self.enabled:
            return PatternMatch(False, 0.0, 0.0, 0, reason="memória de padrões desativada")
        records = self.db_manager.get_market_patterns(symbol=symbol, strategy=strategy, limit=5000)
        candidates = []
        for record in records:
            outcome_atr = _finite(record.outcome_atr)
            sample_size = int(record.sample_size or 1)
            if self.require_profitable and (outcome_atr < self.min_outcome_atr or sample_size < self.min_samples):
                continue
            distance = self._distance(signature, record.signature_json or {})
            candidates.append((distance, outcome_atr, sample_size, record))
        if not candidates:
            return PatternMatch(False, 0.0, 0.0, 0, reason="nenhum padrão histórico elegível")
        distance, outcome_atr, sample_size, record = min(candidates, key=lambda item: item[0])
        if distance > self.max_distance:
            return PatternMatch(False, distance, outcome_atr, sample_size, int(record.id), "padrão mais próximo fora da distância máxima")
        return PatternMatch(True, distance, outcome_atr, sample_size, int(record.id), "padrão histórico compatível")

    def record_completed_pattern(
        self,
        symbol: str,
        signature: Dict[str, float],
        entry_price: float,
        atr: float,
        outcome_atr: float,
        outcome_label: int,
        strategy: str = "pullback",
        source_observation_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Persiste somente padrões já encerrados e rotulados por resultado futuro."""
        if not self.enabled:
            return None
        return self.db_manager.create_market_pattern({
            "symbol": symbol,
            "strategy": strategy,
            "pattern_type": "pullback" if strategy == "pullback" else strategy,
            "signature_json": {name: _finite(signature.get(name)) for name in PATTERN_FEATURES},
            "entry_price": _finite(entry_price),
            "atr": _finite(atr),
            "outcome_atr": _finite(outcome_atr),
            "outcome_label": int(outcome_label),
            "sample_size": 1,
            "source_observation_id": source_observation_id,
            "metadata_json": metadata or {},
        })
