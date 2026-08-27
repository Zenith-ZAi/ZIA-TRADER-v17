from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from core.dataset_integrity import DatasetIntegrityError, sha256_frame, validate_ohlcv
from database_manager import DatabaseManager


def valid_frame(rows: int = 6) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=rows, freq="h", tz="UTC")
    close = pd.Series([100.0 + value for value in range(rows)], index=index)
    return pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 100.0},
        index=index,
    )


def test_dataset_integrity_and_hash_are_deterministic():
    data = valid_frame()
    report = validate_ohlcv(data, timeframe="1h", require_closed=True)
    assert report["rows"] == 6
    assert report["gaps"] == 0
    assert sha256_frame(data) == sha256_frame(data.copy())

    duplicated = pd.concat([data, data.iloc[[-1]]])
    with pytest.raises(DatasetIntegrityError, match="duplicados"):
        validate_ohlcv(duplicated, timeframe="1h")


def test_decision_snapshot_is_idempotent_and_updates_after_context(tmp_path: Path):
    manager = DatabaseManager(f"sqlite:///{tmp_path / 'snapshots.db'}")
    manager.create_tables()
    payload = {
        "snapshot_id": "snap-test-001",
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "mode": "historical-replay",
        "action": "hold",
        "candidate_action": "buy",
        "confidence": 0.62,
        "gate_status": "blocked",
        "dataset_sha256": "dataset-hash",
        "feature_hash": "feature-hash",
        "before_context": {"signal": {"action": "hold"}},
    }
    first = manager.create_decision_snapshot(payload)
    second = manager.create_decision_snapshot(payload)
    assert first.id == second.id
    updated = manager.update_decision_snapshot_after("snap-test-001", {"future_return": 0.01, "label": 1})
    assert updated is not None
    rows = manager.list_decision_snapshots("BTCUSDT")
    assert len(rows) == 1
    assert rows[0]["dataset_sha256"] == "dataset-hash"
    assert rows[0]["after_context"]["label"] == 1
