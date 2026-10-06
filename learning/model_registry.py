"""Acesso controlado às tabelas ModelRegistry/ModelMetric existentes."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import text

from database import ModelMetric, ModelRegistry


_REGISTERABLE_STATUSES = {"candidate", "rejected"}
_ARTIFACT_FILES = ("rf_model.joblib", "xgb_model.joblib", "ensemble_metadata.json")


def artifact_sha256(model_dir: str | Path) -> str:
    """Hash ordenado dos artefatos de inferência do Ensemble."""
    root = Path(model_dir)
    digest = hashlib.sha256()
    found = False
    for name in _ARTIFACT_FILES:
        path = root / name
        if path.is_file():
            found = True
            digest.update(name.encode("utf-8"))
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
    if not found:
        raise FileNotFoundError(f"nenhum artefato conhecido em {root}")
    return digest.hexdigest()


def _safe_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _safe_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_json(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if value is None or isinstance(value, (str, int)):
        return value
    return str(value)


def _metric_rows(version: str, report: dict[str, Any]) -> list[ModelMetric]:
    rows: list[ModelMetric] = []

    def append_numeric(values: Any, split: str, regime: str) -> None:
        if not isinstance(values, dict):
            return
        for key, value in values.items():
            if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
                continue
            number = float(value)
            if math.isfinite(number):
                rows.append(ModelMetric(
                    model_version=version,
                    metric_name=str(key)[:64],
                    regime=str(regime)[:64],
                    split=str(split)[:32],
                    metric_value=number,
                ))

    append_numeric(report.get("validation"), "validation", "all")
    append_numeric(report.get("test"), "test", "all")
    append_numeric(report.get("validation_calibration"), "validation_calibration", "all")
    append_numeric(report.get("test_calibration"), "test_calibration", "all")
    walk_forward = report.get("walk_forward", report)
    aggregate = walk_forward.get("aggregate", {})
    append_numeric(aggregate.get("model_classification"), "walk_forward", "all")
    model_returns = (aggregate.get("strategies") or {}).get("model", {})
    append_numeric(model_returns, "walk_forward", "all")
    for regime, values in (walk_forward.get("by_regime") or {}).items():
        append_numeric(values.get("model_classification"), "walk_forward", str(regime))
        append_numeric((values.get("strategies") or {}).get("model_net"), "walk_forward", str(regime))
    return rows


class ModelRegistryStore:
    """Transações pequenas e explícitas sobre o registry; nunca executa ordens."""

    def __init__(self, db_manager: Any):
        self.db_manager = db_manager

    def register(
        self,
        *,
        model_name: str,
        version: str,
        artifact_hash: str,
        dataset_hash: str,
        metrics_oos: dict[str, Any],
        training_config: dict[str, Any],
        status: str = "candidate",
    ) -> ModelRegistry:
        if status not in _REGISTERABLE_STATUSES:
            raise ValueError("versão deve ser registrada como candidate ou rejected; use activate/rollback para transições")
        if len(str(artifact_hash)) != 64 or len(str(dataset_hash)) != 64:
            raise ValueError("hash SHA-256 inválido")
        db = self.db_manager.SessionLocal()
        try:
            existing = db.query(ModelRegistry).filter(ModelRegistry.version == str(version)).first()
            if existing:
                if existing.artifact_sha256 != artifact_hash or existing.dataset_sha256 != dataset_hash:
                    raise ValueError("versão já registrada com hashes diferentes")
                return existing
            row = ModelRegistry(
                model_name=str(model_name)[:128],
                version=str(version)[:128],
                artifact_sha256=str(artifact_hash),
                dataset_sha256=str(dataset_hash),
                metrics_oos_json=_safe_json(metrics_oos),
                training_config_json=_safe_json(training_config),
                status=status,
            )
            db.add(row)
            db.flush()
            db.add_all(_metric_rows(str(version), metrics_oos))
            db.commit()
            db.refresh(row)
            return row
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def active_version(self, model_name: str) -> str | None:
        db = self.db_manager.SessionLocal()
        try:
            row = (
                db.query(ModelRegistry)
                .filter(ModelRegistry.model_name == str(model_name), ModelRegistry.status == "active")
                .order_by(ModelRegistry.registered_at.desc())
                .first()
            )
            return str(row.version) if row else None
        finally:
            db.close()

    def activate(self, version: str) -> None:
        """Ativa somente registro já criado como candidate após todos os gates."""
        db = self.db_manager.SessionLocal()
        try:
            candidate = db.query(ModelRegistry).filter(ModelRegistry.version == str(version)).with_for_update().first()
            if candidate is None or candidate.status != "candidate":
                raise ValueError("apenas um candidato registrado pode ser ativado")
            if db.bind is not None and db.bind.dialect.name == "postgresql":
                db.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:model_name, 0))"),
                    {"model_name": candidate.model_name},
                )
            active_rows = db.query(ModelRegistry).filter(
                ModelRegistry.model_name == candidate.model_name,
                ModelRegistry.status == "active",
            ).with_for_update().all()
            for row in active_rows:
                row.status = "superseded"
            candidate.status = "active"
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def set_status(self, version: str, status: str) -> None:
        if status != "rejected":
            raise ValueError("set_status só pode rejeitar um candidato; use activate/mark_rollback")
        db = self.db_manager.SessionLocal()
        try:
            row = db.query(ModelRegistry).filter(ModelRegistry.version == str(version)).with_for_update().first()
            if row is None:
                raise LookupError(f"versão não encontrada: {version}")
            if row.status not in {"candidate", "rejected"}:
                raise ValueError("somente candidate pode ser rejeitado por set_status")
            row.status = status
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def mark_rollback(self, current_version: str, restored_version: str | None) -> None:
        """Quarentena do modelo degradado e reativação do backup comprovado."""
        db = self.db_manager.SessionLocal()
        try:
            current = db.query(ModelRegistry).filter(ModelRegistry.version == str(current_version)).with_for_update().first()
            if current is None:
                raise LookupError(f"versão ativa não encontrada: {current_version}")
            if current.status != "active":
                raise ValueError("rollback só pode iniciar a partir da versão active")
            current.status = "drift_hold"
            if restored_version:
                if str(restored_version) == str(current_version):
                    raise ValueError("a versão sob drift não pode ser sua própria restauração")
                restored = db.query(ModelRegistry).filter(ModelRegistry.version == str(restored_version)).with_for_update().first()
                if restored is None or restored.model_name != current.model_name:
                    raise LookupError("versão de rollback não encontrada para o mesmo modelo")
                active_rows = db.query(ModelRegistry).filter(
                    ModelRegistry.model_name == current.model_name,
                    ModelRegistry.status == "active",
                    ModelRegistry.version != str(current_version),
                    ModelRegistry.version != str(restored_version),
                ).with_for_update().all()
                for row in active_rows:
                    row.status = "superseded"
                restored.status = "active"
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
