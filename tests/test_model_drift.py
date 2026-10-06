from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from learning.model_registry import artifact_sha256
from learning.model_drift import (
    _restore_backup,
    assess_drift,
    build_drift_reference,
    population_stability_index,
)


def test_reference_distribution_has_near_zero_psi_for_same_window():
    values = np.linspace(-1.0, 1.0, 100)
    reference_frame = pd.DataFrame({"feature_a": values, "feature_b": values ** 2})
    reference = build_drift_reference(reference_frame, bins=10)
    report = assess_drift(reference, reference_frame)
    assert report["hold"] is False
    assert report["max_psi"] < 1e-6
    assert population_stability_index([0.5, 0.5], [0.5, 0.5]) < 1e-9


def test_data_or_performance_drift_requires_persistent_hold():
    reference_frame = pd.DataFrame({"feature_a": np.linspace(-1.0, 1.0, 100)})
    reference = build_drift_reference(reference_frame)
    shifted = pd.DataFrame({"feature_a": np.linspace(5.0, 7.0, 100)})
    report = assess_drift(
        reference,
        shifted,
        baseline_metrics={"balanced_accuracy": 0.75, "brier_score": 0.20},
        recent_metrics={"balanced_accuracy": 0.60, "brier_score": 0.28},
    )
    assert report["hold"] is True
    assert report["data_drift"] is True
    assert report["performance_drift"] is True
    assert report["status"] == "drift_detected"


def test_backup_restore_returns_prior_model_version(tmp_path):
    model_dir = tmp_path / "models"
    backup = model_dir / "rollback_previous"
    backup.mkdir(parents=True)
    model_dir.mkdir(exist_ok=True)
    for name in ("rf_model.joblib", "xgb_model.joblib"):
        (backup / name).write_bytes((name + "-prior").encode())
        (model_dir / name).write_bytes((name + "-candidate").encode())
    (backup / "ensemble_metadata.json").write_text(json.dumps({"model_version": "previous-v1"}), encoding="utf-8")
    (model_dir / "ensemble_metadata.json").write_text(json.dumps({"model_version": "candidate-v2"}), encoding="utf-8")

    restored, version = _restore_backup(model_dir, backup, artifact_sha256(backup))
    assert restored is True
    assert version == "previous-v1"
    assert (model_dir / "rf_model.joblib").read_bytes() == (backup / "rf_model.joblib").read_bytes()


def test_backup_with_unexpected_hash_is_not_restored(tmp_path):
    model_dir = tmp_path / "models"
    backup = model_dir / "rollback_previous"
    backup.mkdir(parents=True)
    for name in ("rf_model.joblib", "xgb_model.joblib", "ensemble_metadata.json"):
        (backup / name).write_bytes((name + "-prior").encode())
        (model_dir / name).write_bytes((name + "-candidate").encode())
    with pytest.raises(ValueError, match="hash do backup não confere"):
        _restore_backup(model_dir, backup, "0" * 64)
    assert (model_dir / "rf_model.joblib").read_bytes() == b"rf_model.joblib-candidate"
