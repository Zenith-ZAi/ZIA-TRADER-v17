import json

import numpy as np
import pandas as pd
import pytest

from ai.ensemble_model import EnsembleModel
from ai.feature_pipeline import MODEL_FEATURE_COLUMNS, build_feature_frame, build_supervised_dataset
from learning.model_registry import artifact_sha256


def make_fixture(length: int = 240) -> pd.DataFrame:
    index = pd.date_range("2025-01-01", periods=length, freq="h")
    close = 100.0 + np.sin(np.arange(length) / 3.0) * 2.0 + np.arange(length) * 0.01
    open_price = np.roll(close, 1)
    open_price[0] = close[0]
    high = np.maximum(open_price, close) + 0.5
    low = np.minimum(open_price, close) - 0.5
    volume = 1000.0 + (np.arange(length) % 11) * 25.0
    return pd.DataFrame({"open": open_price, "high": high, "low": low, "close": close, "volume": volume}, index=index)


def test_feature_pipeline_has_stable_causal_schema():
    data = make_fixture()
    features = build_feature_frame(data)
    assert list(features.columns) == MODEL_FEATURE_COLUMNS
    assert len(features) == len(data)
    changed = data.copy()
    changed.iloc[-1, changed.columns.get_loc("close")] *= 1.5
    changed_features = build_feature_frame(changed)
    pd.testing.assert_frame_equal(features.iloc[:-1], changed_features.iloc[:-1])


def test_supervised_dataset_uses_future_only_for_labels():
    data = make_fixture()
    X, y = build_supervised_dataset(data, horizon=3)
    assert list(X.columns) == MODEL_FEATURE_COLUMNS
    assert len(X) == len(y)
    assert set(y.unique()) <= {0, 1, 2}
    assert len(set(y.unique())) == 3


def test_future_change_cannot_change_past_features_but_changes_its_future_label():
    length = 240
    index = pd.date_range("2025-01-01", periods=length, freq="h", tz="UTC")
    close = np.full(length, 100.0)
    open_price = close.copy()
    high = close + 1.0
    low = close - 1.0
    volume = 1000.0 + (np.arange(length) % 7) * 10.0
    original = pd.DataFrame(
        {"open": open_price, "high": high, "low": low, "close": close, "volume": volume}, index=index
    )
    changed = original.copy()
    target_row = 180
    future_row = target_row + 3
    changed.iloc[future_row, changed.columns.get_loc("close")] = 102.0
    changed.iloc[future_row, changed.columns.get_loc("high")] = 103.0

    X_original, y_original = build_supervised_dataset(original, horizon=3)
    X_changed, y_changed = build_supervised_dataset(changed, horizon=3)

    pd.testing.assert_frame_equal(X_original.loc[: index[target_row]], X_changed.loc[: index[target_row]])
    assert y_original.loc[index[target_row]] == 1
    assert y_changed.loc[index[target_row]] == 2


def test_ensemble_train_save_load_and_predict(tmp_path):
    X, y = build_supervised_dataset(make_fixture(), horizon=3)
    model_dir = tmp_path / "models"
    model = EnsembleModel(str(model_dir))
    metadata = model.train(X, y, {"test": True})
    assert model.is_trained is True
    assert metadata["feature_columns"] == MODEL_FEATURE_COLUMNS
    action, confidence = model.predict(X.tail(1))
    assert action in {"buy", "sell", "hold"}
    assert 0.0 <= confidence <= 1.0

    loaded = EnsembleModel(str(model_dir))
    assert loaded.is_trained is True
    action_without_drift = loaded.predict(X.tail(1))
    assert action_without_drift[0] in {"buy", "sell", "hold"}
    probabilities = loaded.predict_proba(X.tail(4))
    assert probabilities.shape == (4, 3)
    assert np.allclose(probabilities.sum(axis=1), 1.0)
    assert loaded.predict(pd.DataFrame([{"close": 1.0}])) == ("hold", 0.5)
    (model_dir / "drift_status.json").write_text(json.dumps({"hold": True}), encoding="utf-8")
    assert loaded.predict(X.tail(1)) == ("hold", 0.5)
    (model_dir / "drift_status.json").unlink()
    assert loaded.predict(X.tail(1)) == action_without_drift
    (model_dir / "drift_status.json").write_text("{corrompido", encoding="utf-8")
    assert loaded.predict(X.tail(1)) == ("hold", 0.5)


def test_ensemble_training_is_reproducible_for_fixed_seed(tmp_path):
    X, y = build_supervised_dataset(make_fixture(), horizon=3)
    first = EnsembleModel(str(tmp_path / "first"), random_state=19)
    second = EnsembleModel(str(tmp_path / "second"), random_state=19)
    first.train(X, y)
    second.train(X, y)
    np.testing.assert_allclose(first.predict_proba(X.tail(12)), second.predict_proba(X.tail(12)), rtol=0.0, atol=0.0)


def test_untrained_ensemble_does_not_emit_synthetic_probabilities(tmp_path):
    model = EnsembleModel(str(tmp_path / "missing"))
    assert model.predict(pd.DataFrame()) == ("hold", 0.5)
    with pytest.raises(RuntimeError, match="Ensemble indisponível"):
        model.predict_proba(pd.DataFrame([{}]))


@pytest.mark.parametrize(
    "probabilities",
    [
        np.asarray([[0.2, 0.2, np.nan]]),
        np.asarray([[0.2, 0.2, 0.2]]),
        np.asarray([[1.2, -0.1, -0.1]]),
    ],
)
def test_ensemble_rejects_invalid_raw_class_probabilities(probabilities):
    class BrokenModel:
        classes_ = np.asarray([0, 1, 2])

        def predict_proba(self, features):
            return probabilities

    with pytest.raises(ValueError):
        EnsembleModel._aligned_proba_matrix(BrokenModel(), pd.DataFrame([{}]))


def test_runtime_ensemble_requires_active_registry_version_and_matching_hash(tmp_path):
    X, y = build_supervised_dataset(make_fixture(), horizon=3)
    model_dir = tmp_path / "models"
    trained = EnsembleModel(str(model_dir))
    metadata = trained.train(X, y)
    metadata.update({
        "model_version": "ensemble-test-v1",
        "dataset_sha256": "a" * 64,
        "decision": "accepted",
        "registry_status": "active",
    })
    (model_dir / "ensemble_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    expected_hash = artifact_sha256(model_dir)

    class Registry:
        def __init__(self, approved_hash):
            self.approved_hash = approved_hash

        def verify_active_artifact(self, model_name, version, artifact_hash):
            return (model_name, version, artifact_hash) == ("ensemble", "ensemble-test-v1", self.approved_hash)

    loaded = EnsembleModel(str(model_dir), registry_store=Registry(expected_hash), require_active_registry=True)
    assert loaded.is_trained
    assert loaded.load_status == "loaded_active"

    rejected = EnsembleModel(str(model_dir), registry_store=Registry("0" * 64), require_active_registry=True)
    assert not rejected.is_trained
    assert rejected.load_status == "rejected_incompatible_or_unapproved"
