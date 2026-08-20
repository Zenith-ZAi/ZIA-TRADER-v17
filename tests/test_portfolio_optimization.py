import pandas as pd
import pytest

from execution.cost_aware_executor import CostAwareExecutor
from risk.correlation_manager import CorrelationManager


def test_correlation_manager_finds_low_correlation_pairs_and_weights():
    index = pd.date_range("2025-01-01", periods=20, freq="D", tz="UTC")
    base = pd.Series([100 + i for i in range(20)], index=index)
    inverse = pd.Series([120 - i for i in range(20)], index=index)
    flat = pd.Series([100 + (i % 2) for i in range(20)], index=index)
    manager = CorrelationManager(low_correlation_threshold=0.3, max_weight=1.0)
    recommendation = manager.recommend({"BTC/USDT": base, "ETH/USDT": base * 1.1, "USD/JPY": inverse, "EUR/USD": flat})
    assert recommendation["weights"]
    assert abs(sum(recommendation["weights"].values()) - 1.0) < 1e-9
    assert recommendation["low_correlation_pairs"]
    assert any(abs(pair["correlation"]) < 0.3 for pair in recommendation["low_correlation_pairs"])


def test_cost_aware_executor_selects_liquid_window_and_adjusts_quantity():
    executor = CostAwareExecutor(max_spread_bps=30, max_slippage_bps=20, max_book_impact=0.1)
    observations = [
        {"timestamp": "illiquid", "snapshot": {"bid": 99.0, "ask": 101.0, "asks": [{"price": 101.0, "quantity": 1.0}], "bids": [{"price": 99.0, "quantity": 1.0}]}},
        {"timestamp": "liquid", "snapshot": {"bid": 99.99, "ask": 100.01, "asks": [{"price": 100.01, "quantity": 100.0}], "bids": [{"price": 99.99, "quantity": 100.0}]}},
    ]
    result = executor.choose_execution_window(observations, "buy", 1.0)
    assert result["selected"]["timestamp"] == "liquid"
    adjusted = executor.adjust_quantity(observations[1]["snapshot"], "buy", 1000.0)
    assert adjusted["adjusted_quantity"] == pytest.approx(110.0)
    assert adjusted["reduced"] is True
