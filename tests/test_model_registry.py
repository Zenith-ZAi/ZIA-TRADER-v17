from __future__ import annotations

import os
import uuid

import pytest

from database import ModelMetric, ModelRegistry
from database_manager import DatabaseManager
from learning.model_registry import ModelRegistryStore, artifact_sha256


def _hash(char: str) -> str:
    return char * 64


def test_registry_records_candidate_metrics_and_only_activates_candidate(tmp_path):
    manager = DatabaseManager(f"sqlite:///{tmp_path / 'registry.db'}")
    manager.create_tables()
    store = ModelRegistryStore(manager)
    metrics = {
        "test_calibration": {"brier_score": 0.12, "ece": 0.05},
        "aggregate": {
            "model_classification": {"f1_macro": 0.44, "brier_score": 0.12},
            "strategies": {"model": {"cumulative_net_return": 0.03}},
        },
        "by_regime": {
            "low_vol_uptrend": {
                "model_classification": {"f1_macro": 0.50},
                "strategies": {"model_net": {"cumulative_net_return": 0.02}},
            }
        },
    }
    with pytest.raises(ValueError, match="candidate ou rejected"):
        store.register(
            model_name="ensemble",
            version="bypass-activation",
            artifact_hash=_hash("a"),
            dataset_hash=_hash("b"),
            metrics_oos=metrics,
            training_config={"seed": 42},
            status="active",
        )
    store.register(
        model_name="ensemble",
        version="candidate-one",
        artifact_hash=_hash("a"),
        dataset_hash=_hash("b"),
        metrics_oos=metrics,
        training_config={"seed": 42, "purge_gap": 3},
        status="candidate",
    )
    assert store.active_version("ensemble") is None
    with pytest.raises(ValueError, match="candidato"):
        store.activate("missing-version")
    store.activate("candidate-one")
    assert store.active_version("ensemble") == "candidate-one"

    store.register(
        model_name="ensemble",
        version="candidate-two",
        artifact_hash=_hash("c"),
        dataset_hash=_hash("d"),
        metrics_oos=metrics,
        training_config={"seed": 7},
        status="candidate",
    )
    store.activate("candidate-two")
    assert store.active_version("ensemble") == "candidate-two"
    store.mark_rollback("candidate-two", "candidate-one")
    assert store.active_version("ensemble") == "candidate-one"

    session = manager.SessionLocal()
    try:
        statuses = {row.version: row.status for row in session.query(ModelRegistry).all()}
        assert statuses == {"candidate-one": "active", "candidate-two": "drift_hold"}
        metric_rows = session.query(ModelRegistry).filter_by(version="candidate-one").one()
        assert metric_rows.metrics_oos_json["aggregate"]["model_classification"]["f1_macro"] == 0.44
        stored_metrics = session.query(ModelMetric).filter_by(model_version="candidate-one").all()
        assert any(row.metric_name == "f1_macro" and row.split == "walk_forward" for row in stored_metrics)
        assert any(row.metric_name == "brier_score" and row.split == "test_calibration" for row in stored_metrics)
        assert any(row.regime == "low_vol_uptrend" for row in stored_metrics)
    finally:
        session.close()
        manager.engine.dispose()


def test_artifact_hash_changes_with_model_bytes(tmp_path):
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    (model_dir / "rf_model.joblib").write_bytes(b"rf-v1")
    (model_dir / "xgb_model.joblib").write_bytes(b"xgb-v1")
    (model_dir / "ensemble_metadata.json").write_text("{}", encoding="utf-8")
    first = artifact_sha256(model_dir)
    (model_dir / "xgb_model.joblib").write_bytes(b"xgb-v2")
    assert artifact_sha256(model_dir) != first


def test_registry_postgresql_promotion_and_rollback_when_configured():
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL não configurada; integração executada no CI PostgreSQL")
    model_name = f"registry-integration-{uuid.uuid4().hex}"
    prior_version = f"prior-{uuid.uuid4().hex}"
    candidate_version = f"candidate-{uuid.uuid4().hex}"
    manager = DatabaseManager(database_url)
    try:
        manager.create_tables()
        store = ModelRegistryStore(manager)
        metrics = {"walk_forward": {"aggregate": {"model_classification": {"f1_macro": 0.6}}}}
        for version, char in ((prior_version, "e"), (candidate_version, "f")):
            store.register(
                model_name=model_name,
                version=version,
                artifact_hash=_hash(char),
                dataset_hash=_hash("a" if char == "e" else "b"),
                metrics_oos=metrics,
                training_config={"seed": 42},
                status="candidate",
            )
        store.activate(prior_version)
        store.activate(candidate_version)
        assert store.active_version(model_name) == candidate_version
        store.mark_rollback(candidate_version, prior_version)
        assert store.active_version(model_name) == prior_version
        session = manager.SessionLocal()
        try:
            statuses = {
                row.version: row.status
                for row in session.query(ModelRegistry).filter(ModelRegistry.model_name == model_name).all()
            }
            assert statuses == {prior_version: "active", candidate_version: "drift_hold"}
        finally:
            session.close()
    finally:
        cleanup = manager.SessionLocal()
        try:
            cleanup.query(ModelMetric).filter(ModelMetric.model_version.in_([prior_version, candidate_version])).delete(synchronize_session=False)
            cleanup.query(ModelRegistry).filter(ModelRegistry.version.in_([prior_version, candidate_version])).delete(synchronize_session=False)
            cleanup.commit()
        except Exception:
            cleanup.rollback()
            raise
        finally:
            cleanup.close()
            manager.engine.dispose()
