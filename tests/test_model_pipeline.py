import numpy as np
import pandas as pd

from ai.ensemble_model import EnsembleModel
from ai.feature_pipeline import MODEL_FEATURE_COLUMNS, build_feature_frame, build_supervised_dataset


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
    assert loaded.predict(X.tail(1))[0] in {"buy", "sell", "hold"}
    assert loaded.predict(pd.DataFrame([{"close": 1.0}])) == ("hold", 0.5)
