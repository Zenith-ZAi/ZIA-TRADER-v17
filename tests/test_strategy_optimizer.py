import asyncio

import numpy as np
import pandas as pd

from config.settings import Settings
from risk.strategy_optimizer import OptimizationBudget, StrategyOptimizer


def make_frame(rows=260):
    index = pd.date_range("2025-01-01", periods=rows, freq="h", tz="UTC")
    close = 100.0 + np.sin(np.linspace(0, 18, rows)) + np.linspace(0, 3, rows)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "volume": 1000.0,
        },
        index=index,
    )


def test_optimizer_respects_budget_and_temporal_split(tmp_path):
    settings = Settings(
        DATABASE_URL=f"sqlite:///{tmp_path / 'optimizer.db'}",
        PULLBACK_STRATEGY_ENABLED=False,
        BACKTEST_WARMUP_BARS=40,
        FRICTION_ENABLED=False,
        METRICS_PERIODS_PER_YEAR=8760,
    )
    optimizer = StrategyOptimizer(
        settings,
        budget=OptimizationBudget(max_evaluations=3, max_seconds=60, validation_fraction=0.25, min_trades=0),
    )
    result = asyncio.run(
        optimizer.optimize_async(
            "BTC/USDT",
            make_frame(),
            search_space={
                "MIN_CONFIDENCE_THRESHOLD": (0.6, 0.7),
                "BACKTEST_STOP_LOSS_PCT": (0.01, 0.02),
            },
        )
    )
    assert result["status"] == "ok"
    assert len(result["evaluations"]) <= 2
    assert result["window_start"] < result["window_end"]
    assert result["baseline"]["validation"]["trades_executed"] >= 0
    assert len(result["top10"]) <= 2
