"""Métricas de risco reproduzíveis para retornos e curvas de capital."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable, Sequence

import numpy as np


@dataclass(frozen=True)
class RiskMetrics:
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    maximum_drawdown: float
    annualized_return: float
    observations: int
    risk_free_rate_annual: float
    periods_per_year: int

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)


class SharpeAnalyzer:
    """Calcula métricas sem usar dados futuros.

    ``risk_free_rate`` é anual; ele é convertido para a taxa por observação
    antes do cálculo. Para candles horários, o consumidor deve informar o
    número de períodos anuais adequado. O default 252 é apropriado para
    retornos diários e também mantém compatibilidade com o protocolo existente.
    """

    def __init__(self, risk_free_rate: float = 0.0, periods_per_year: int = 252):
        self.risk_free_rate = float(risk_free_rate)
        self.periods_per_year = max(1, int(periods_per_year))

    @staticmethod
    def _clean(values: Iterable[float]) -> np.ndarray:
        array = np.asarray(list(values), dtype=float)
        return array[np.isfinite(array)]

    @staticmethod
    def _maximum_drawdown(equity: Sequence[float]) -> float:
        curve = np.asarray(equity, dtype=float)
        curve = curve[np.isfinite(curve)]
        if curve.size == 0:
            return 0.0
        running_max = np.maximum.accumulate(curve)
        drawdowns = (curve - running_max) / np.maximum(np.abs(running_max), 1e-12)
        return float(np.min(drawdowns))

    def analyze(self, returns: Iterable[float], equity_curve: Iterable[float] | None = None) -> dict[str, float | int]:
        values = self._clean(returns)
        if values.size == 0:
            metrics = RiskMetrics(0.0, 0.0, 0.0, 0.0, 0.0, 0, self.risk_free_rate, self.periods_per_year)
            return metrics.to_dict()
        periodic_rf = self.risk_free_rate / self.periods_per_year
        excess = values - periodic_rf
        volatility = float(np.std(excess, ddof=1)) if values.size > 1 else 0.0
        sharpe = float(np.mean(excess) / volatility * np.sqrt(self.periods_per_year)) if volatility > 0 else 0.0
        downside = excess[excess < 0.0]
        downside_deviation = float(np.sqrt(np.mean(np.square(downside)))) if downside.size else 0.0
        sortino = float(np.mean(excess) / downside_deviation * np.sqrt(self.periods_per_year)) if downside_deviation > 0 else 0.0
        curve = list(equity_curve) if equity_curve is not None else list(np.cumprod(1.0 + values))
        maximum_drawdown = self._maximum_drawdown(curve)
        growth = float(np.prod(1.0 + values)) if np.all(1.0 + values > 0.0) else 0.0
        annualized_return = float(growth ** (self.periods_per_year / values.size) - 1.0) if growth > 0 else -1.0
        calmar = float(annualized_return / abs(maximum_drawdown)) if maximum_drawdown < 0 else 0.0
        metrics = RiskMetrics(
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            maximum_drawdown=maximum_drawdown,
            annualized_return=annualized_return,
            observations=int(values.size),
            risk_free_rate_annual=self.risk_free_rate,
            periods_per_year=self.periods_per_year,
        )
        return metrics.to_dict()
