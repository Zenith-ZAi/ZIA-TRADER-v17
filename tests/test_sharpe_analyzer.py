import asyncio

import numpy as np
import pandas as pd

from config.settings import Settings
from core.backtest_engine import BacktestEngine
from risk.sharpe_analyzer import SharpeAnalyzer


def test_sharpe_analyzer_returns_all_risk_metrics():
    analyzer = SharpeAnalyzer(risk_free_rate=0.0, periods_per_year=252)
    metrics = analyzer.analyze([0.01, -0.005, 0.008, 0.004])
    assert metrics["observations"] == 4
    assert np.isfinite(metrics["sharpe_ratio"])
    assert "sortino_ratio" in metrics
    assert "calmar_ratio" in metrics
    assert metrics["maximum_drawdown"] <= 0.0


def test_backtest_emits_extended_risk_metrics(tmp_path):
    index = pd.date_range("2025-01-01", periods=120, freq="h", tz="UTC")
    close = np.linspace(100.0, 110.0, len(index))
    data = pd.DataFrame({
        "open": close,
        "high": close * 1.001,
        "low": close * 0.999,
        "close": close,
        "volume": 1000.0,
    }, index=index)
    settings = Settings(
        DATABASE_URL=f"sqlite:///{tmp_path / 'metrics.db'}",
        PULLBACK_STRATEGY_ENABLED=False,
        BACKTEST_WARMUP_BARS=40,
        METRICS_PERIODS_PER_YEAR=8760,
        FRICTION_ENABLED=False,
    )
    result = asyncio.run(BacktestEngine(settings, None).run("BTC/USDT", data))
    assert result["status"] == "ok"
    assert "sortino_ratio" in result
    assert "calmar_ratio" in result
    assert "risk_metrics" in result
    assert isinstance(result["trade_sharpe_feedback"], list)


def test_sharpe_feedback_recommends_reoptimization_on_schedule():
    from risk.sharpe_feedback import SharpeFeedback

    feedback = SharpeFeedback(SharpeAnalyzer(periods_per_year=252), reoptimize_every=2)
    first = feedback.record(0.01)
    second = feedback.record(0.02)
    assert first.should_reoptimize is False
    assert second.should_reoptimize is True
    assert isinstance(second.reward, float)
    assert feedback.snapshot()["trades"] == 2
