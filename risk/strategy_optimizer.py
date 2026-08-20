"""Busca temporal segura de parâmetros para estratégias existentes."""

from __future__ import annotations

import asyncio
import itertools
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping

import pandas as pd

from core.backtest_engine import BacktestEngine


DEFAULT_SEARCH_SPACE: dict[str, tuple[Any, ...]] = {
    "PULLBACK_EMA_PERIOD": (100, 200),
    "MIN_CONFIDENCE_THRESHOLD": (0.60, 0.70),
    "BACKTEST_STOP_LOSS_PCT": (0.01, 0.02),
    "BACKTEST_TAKE_PROFIT_PCT": (0.03, 0.05),
}


@dataclass(frozen=True)
class OptimizationBudget:
    max_evaluations: int = 32
    max_seconds: float = 540.0
    validation_fraction: float = 0.30
    min_trades: int = 3


class StrategyOptimizer:
    """Executa backtests candidatos sem enviar ordens e sem usar dados futuros."""

    def __init__(self, settings: Any, db_manager=None, budget: OptimizationBudget | None = None):
        self.settings = settings
        self.db_manager = db_manager
        self.budget = budget or OptimizationBudget()

    @staticmethod
    def _candidate_settings(settings: Any, params: Mapping[str, Any]) -> Any:
        allowed = set(DEFAULT_SEARCH_SPACE)
        unknown = set(params) - allowed
        if unknown:
            raise ValueError(f"Parâmetros não permitidos no optimizer: {sorted(unknown)}")
        return settings.model_copy(update=dict(params), deep=True)

    @staticmethod
    def _window(data: pd.DataFrame, data_window_bars: int | None) -> pd.DataFrame:
        frame = data.copy().sort_index()
        if data_window_bars and len(frame) > int(data_window_bars):
            frame = frame.tail(int(data_window_bars))
        return frame

    @staticmethod
    def _score(metrics: Mapping[str, Any], min_trades: int) -> float:
        sharpe = float(metrics.get("sharpe_ratio", 0.0) or 0.0)
        drawdown = abs(float(metrics.get("max_drawdown", 0.0) or 0.0))
        trades = int(metrics.get("trades_executed", 0) or 0)
        penalty = 0.5 * drawdown
        if trades < min_trades:
            penalty += 1.0
        return float(sharpe - penalty)

    async def _evaluate(self, symbol: str, data: pd.DataFrame, params: Mapping[str, Any], strategy_name: str) -> dict[str, Any]:
        candidate_settings = self._candidate_settings(self.settings, params)
        split = max(40, int(len(data) * (1.0 - self.budget.validation_fraction)))
        if split >= len(data):
            split = max(40, len(data) - 1)
        train = data.iloc[:split]
        validation = data.iloc[split:]
        train_result = await BacktestEngine(candidate_settings, self.db_manager).run(symbol, train, strategy_name)
        validation_result = await BacktestEngine(candidate_settings, self.db_manager).run(symbol, validation, strategy_name)
        validation_metrics = {
            "sharpe_ratio": validation_result.get("sharpe_ratio", 0.0),
            "sortino_ratio": validation_result.get("sortino_ratio", 0.0),
            "calmar_ratio": validation_result.get("calmar_ratio", 0.0),
            "max_drawdown": validation_result.get("max_drawdown", 0.0),
            "trades_executed": validation_result.get("trades_executed", 0),
            "return_pct": validation_result.get("return_pct", 0.0),
            "total_fees": validation_result.get("total_fees", 0.0),
        }
        return {
            "params": dict(params),
            "eligible": int(validation_metrics["trades_executed"]) >= self.budget.min_trades,
            "train": {
                "sharpe_ratio": train_result.get("sharpe_ratio", 0.0),
                "max_drawdown": train_result.get("max_drawdown", 0.0),
                "trades_executed": train_result.get("trades_executed", 0),
                "return_pct": train_result.get("return_pct", 0.0),
            },
            "validation": validation_metrics,
            "selection_score": self._score(validation_metrics, self.budget.min_trades),
        }

    async def optimize_async(
        self,
        symbol: str,
        historical_data: pd.DataFrame,
        search_space: Mapping[str, Iterable[Any]] | None = None,
        data_window_bars: int | None = None,
        strategy_name: str = "StrategyOptimizer",
    ) -> dict[str, Any]:
        started = time.perf_counter()
        data = self._window(historical_data, data_window_bars)
        if len(data) < 100:
            return {"status": "insufficient_data", "evaluations": [], "top10": []}
        space = {key: tuple(values) for key, values in (search_space or DEFAULT_SEARCH_SPACE).items()}
        keys = list(space)
        candidates = [dict(zip(keys, values)) for values in itertools.product(*(space[key] for key in keys))]
        candidates = candidates[: max(1, int(self.budget.max_evaluations))]
        baseline_params = {key: getattr(self.settings, key) for key in keys}
        baseline = await self._evaluate(symbol, data, baseline_params, f"{strategy_name} baseline")
        evaluations = []
        timed_out = False
        for params in candidates:
            if params == baseline_params:
                continue
            if len(evaluations) >= max(0, int(self.budget.max_evaluations) - 1):
                break
            if time.perf_counter() - started >= float(self.budget.max_seconds):
                timed_out = True
                break
            evaluations.append(await self._evaluate(symbol, data, params, strategy_name))
        ranked = sorted(
            evaluations,
            key=lambda item: (
                int(bool(item.get("eligible"))),
                float(item["selection_score"]),
                float(item["validation"]["sharpe_ratio"]),
                float(item["validation"]["return_pct"]),
            ),
            reverse=True,
        )
        eligible_count = sum(1 for item in evaluations if item.get("eligible"))
        return {
            "status": "ok",
            "symbol": symbol,
            "strategy": strategy_name,
            "window_bars": len(data),
            "window_start": data.index.min().isoformat(),
            "window_end": data.index.max().isoformat(),
            "validation_fraction": self.budget.validation_fraction,
            "budget": {
                "max_evaluations": self.budget.max_evaluations,
                "max_seconds": self.budget.max_seconds,
                "min_trades": self.budget.min_trades,
            },
            "search_space": {key: list(values) for key, values in space.items()},
            "baseline": baseline,
            "evaluations": evaluations,
            "top10": ranked[:10],
            "eligible_evaluations": eligible_count,
            "selection_warning": None if eligible_count else "nenhuma combinação atingiu o número mínimo de trades; não promover parâmetros automaticamente",
            "timed_out": timed_out,
            "elapsed_seconds": time.perf_counter() - started,
        }

    def optimize(self, *args, **kwargs) -> dict[str, Any]:
        """Interface síncrona para scripts; endpoints assíncronos usam optimize_async."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.optimize_async(*args, **kwargs))
        raise RuntimeError("Use optimize_async dentro de um event loop ativo.")
