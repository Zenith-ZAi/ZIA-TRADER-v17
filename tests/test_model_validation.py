from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from learning.model_validation import (
    _net_returns,
    evaluate_walk_forward,
    make_walk_forward_splits,
    probability_metrics,
    write_validation_report,
)


def make_closed_ohlcv(length: int = 600) -> pd.DataFrame:
    index = pd.date_range("2025-01-01", periods=length, freq="h", tz="UTC")
    positions = np.arange(length, dtype=float)
    close = 100.0 + np.sin(positions / 7.0) * 4.0 + positions * 0.015
    open_price = np.roll(close, 1)
    open_price[0] = close[0]
    high = np.maximum(open_price, close) + 0.5
    low = np.minimum(open_price, close) - 0.5
    return pd.DataFrame({
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": 1000.0 + positions % 17,
    }, index=index)


class ConstantProbabilityModel:
    def __init__(self, model_dir: str, seed: int):
        self.seed = seed

    def train(self, X, y, metadata=None):
        assert len(X) == len(y)
        assert metadata["seed"] == self.seed

    def predict_proba(self, X):
        return np.tile(np.asarray([0.2, 0.6, 0.2]), (len(X), 1))


def test_walk_forward_splits_enforce_purge_embargo_and_chronology():
    splits = make_walk_forward_splits(240, folds=3, min_train_rows=100, purge_gap=5, embargo=4)
    assert len(splits) == 3
    for split in splits:
        assert split["train_start"] == 0
        assert split["train_end"] == split["test_start"] - 9
        assert split["train_end"] >= 100
    for left, right in zip(splits, splits[1:]):
        assert right["test_start"] - left["test_end"] >= 4
        assert right["train_end"] < right["test_start"]


def test_walk_forward_requires_room_for_each_fold():
    try:
        make_walk_forward_splits(30, folds=3, min_train_rows=20, purge_gap=5, embargo=5)
    except ValueError as exc:
        assert "insuficiente" in str(exc)
    else:
        raise AssertionError("splitter não deve criar folds vazios")


def test_walk_forward_requires_purge_and_embargo_at_least_horizon():
    with pytest.raises(ValueError, match=">= horizon"):
        evaluate_walk_forward(
            pd.DataFrame(),
            horizon=3,
            folds=2,
            purge_gap=2,
            embargo=3,
            transaction_cost_bps=10,
            slippage_bps=5,
        )


def test_probability_metrics_are_multiclass_and_emit_reliability_curve():
    truth = np.asarray([0, 1, 2, 1])
    probs = np.asarray([
        [0.8, 0.1, 0.1],
        [0.2, 0.7, 0.1],
        [0.1, 0.2, 0.7],
        [0.1, 0.8, 0.1],
    ])
    metrics = probability_metrics(truth, probs)
    assert metrics["brier_score"] >= 0.0
    assert metrics["ece"] >= 0.0
    assert metrics["accuracy"] == 1.0
    assert len(metrics["reliability_curve"]) == 10
    assert sum(row["count"] for row in metrics["reliability_curve"]) == len(truth)


def test_net_returns_charge_entry_and_final_exit_turnover():
    net, trade_counts = _net_returns(np.asarray([1.0, 1.0]), np.asarray([0.01, 0.01]), total_cost_bps=15.0)
    np.testing.assert_allclose(net, np.asarray([0.0085, 0.0085]))
    assert int(trade_counts.sum()) == 2


def test_walk_forward_returns_baselines_regimes_costs_and_report(tmp_path):
    report = evaluate_walk_forward(
        make_closed_ohlcv(),
        horizon=3,
        folds=3,
        transaction_cost_bps=10.0,
        slippage_bps=5.0,
        seed=17,
        model_factory=ConstantProbabilityModel,
    )
    assert len(report["folds"]) == 3
    assert report["aggregate"]["scored_rows"] > 0
    assert set(report["aggregate"]["strategies"]) == {"model", "buy_and_hold", "deterministic_momentum"}
    assert report["assumptions"]["combined_cost_bps"] == 15.0
    assert report["by_regime"]
    output = write_validation_report(report, tmp_path / "report.md")
    content = output.read_text(encoding="utf-8")
    assert "Reliability curve" in content
    assert "buy_and_hold" in content
