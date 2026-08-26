from __future__ import annotations

import pandas as pd
import pytest

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
