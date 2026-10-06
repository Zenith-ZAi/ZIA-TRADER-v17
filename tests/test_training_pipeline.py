from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from database import ModelRegistry
from database_manager import DatabaseManager
from learning.model_registry import ModelRegistryStore
from learning import training_pipeline
from learning.training_pipeline import train_oos


def test_controlled_training_refuses_insufficient_dataset(tmp_path):
    index = pd.date_range("2026-01-01", periods=100, freq="h", tz="UTC")
    close = pd.Series(range(100, 200), index=index, dtype=float)
    frame = pd.DataFrame({
        "timestamp": index,
        "open": close.to_numpy() - 0.5,
        "high": close.to_numpy() + 1.0,
        "low": close.to_numpy() - 1.0,
        "close": close.to_numpy(),
        "volume": 1000.0,
    })
    path = tmp_path / "too_small.csv"
    frame.to_csv(path, index=False)
    with pytest.raises(ValueError, match="insuficiente"):
        train_oos(path, model_dir=tmp_path / "models")
    assert not (tmp_path / "models" / "ensemble_metadata.json").exists()


def test_training_rejects_zero_horizon_before_reading_dataset(tmp_path):
    with pytest.raises(ValueError, match="horizon deve ser >= 1"):
        train_oos(tmp_path / "missing.csv", horizon=0)


def test_legacy_training_entrypoint_delegates_to_controlled_pipeline(monkeypatch, tmp_path):
    from ai import train_ensemble

    captured = {}

    def fake_train_oos(source, **kwargs):
        captured["source"] = source
        captured.update(kwargs)
        return {"decision": "rejected"}

    monkeypatch.setattr("learning.training_pipeline.train_oos", fake_train_oos)
    result = train_ensemble.train_from_ohlcv(
        "verified.csv",
        model_dir=tmp_path / "models",
        horizon=4,
        seed=31,
        transaction_cost_bps=8.0,
        slippage_bps=3.0,
    )
    assert result["decision"] == "rejected"
    assert captured["source"] == "verified.csv"
    assert captured["horizon"] == 4
    assert captured["seed"] == 31
    assert captured["transaction_cost_bps"] == 8.0
    assert captured["slippage_bps"] == 3.0


def test_candidate_is_not_promoted_when_walk_forward_fails_baseline_gate(monkeypatch, tmp_path):
    # Fixture sintético e fake model somente para testar o gate; não é análise de mercado.
    index = pd.date_range("2025-01-01", periods=480, freq="h", tz="UTC")
    step = np.arange(len(index), dtype=float)
    returns = 0.003 + 0.0005 * np.sin(step / 8.0)
    close = 100.0 * np.cumprod(1.0 + returns)
    open_price = np.roll(close, 1)
    open_price[0] = close[0]
    frame = pd.DataFrame({
        "timestamp": index,
        "open": open_price,
        "high": np.maximum(open_price, close) + 0.1,
        "low": np.minimum(open_price, close) - 0.1,
        "close": close,
        "volume": 1000.0 + (step % 11) * 10.0,
    })
    dataset = tmp_path / "synthetic_gate_fixture.csv"
    frame.to_csv(dataset, index=False)
    model_dir = tmp_path / "candidate-models"
    manager = DatabaseManager(f"sqlite:///{tmp_path / 'training-registry.db'}")
    manager.create_tables()
    registry = ModelRegistryStore(manager)

    score_indices = []

    class FakeCandidate:
        def __init__(self, directory, random_state=42):
            self.directory = Path(directory)

        def train(self, X, y, metadata=None):
            (self.directory / "rf_model.joblib").write_bytes(b"test-only-rf")
            (self.directory / "xgb_model.joblib").write_bytes(b"test-only-xgb")
            return {"feature_columns": list(X.columns), "rows": len(X), **(metadata or {})}

        def predict_proba(self, X):
            score_indices.append(X.index)
            return np.tile(np.asarray([0.005, 0.005, 0.99]), (len(X), 1))

        def predict(self, X):
            return "buy", 0.99

    fake_walk_forward = {
        "aggregate": {
            "model_classification": {"brier_score": 0.001, "ece": 0.01, "balanced_accuracy": 1.0},
            "outperforms_all_baselines": False,
            "strategies": {},
        },
        "folds": [],
        "by_regime": {},
    }
    monkeypatch.setattr(training_pipeline, "EnsembleModel", FakeCandidate)
    monkeypatch.setattr(training_pipeline, "evaluate_walk_forward", lambda *args, **kwargs: fake_walk_forward)
    monkeypatch.setattr(training_pipeline, "write_validation_report", lambda report, destination: Path(destination))

    result = train_oos(
        dataset,
        model_dir=model_dir,
        registry_store=registry,
        report_path=tmp_path / "unused-report.md",
        min_validation_f1=0.30,
    )

    assert result["decision"] == "rejected"
    assert result["registry_status"] == "rejected"
    assert result["validation_metrics"]["f1_macro"] >= 0.30
    assert result["test_metrics"]["sharpe_proxy"] > 0.5
    assert result["calibration_brier"] < 0.2
    assert not (model_dir / "rf_model.joblib").exists()
    assert registry.active_version("ensemble") is None
    assert len(score_indices) == 2
    assert score_indices[0][-1] + pd.Timedelta(hours=3) < score_indices[1][0]
    session = manager.SessionLocal()
    try:
        row = session.query(ModelRegistry).filter_by(version=result["model_version"]).one()
        assert row.status == "rejected"
        assert row.training_config_json["artifact_persisted"] is False
    finally:
        session.close()
        manager.engine.dispose()
