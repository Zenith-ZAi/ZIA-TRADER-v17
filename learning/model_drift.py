"""Monitor de drift de dados/performance com hold persistente e rollback seguro."""
from __future__ import annotations

import argparse
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ai.ensemble_model import EnsembleModel
from ai.train_ensemble import load_ohlcv
from core.dataset_integrity import sha256_file, sha256_frame, validate_ohlcv
from core.feature_pipeline import FeaturePipeline
from learning.model_validation import probability_metrics
from learning.model_registry import artifact_sha256

logger = logging.getLogger(__name__)


def build_drift_reference(features: pd.DataFrame, bins: int = 10) -> dict[str, Any]:
    """Persiste histogramas de referência treinados, sem armazenar linhas OHLCV."""
    if not isinstance(features, pd.DataFrame) or features.empty or bins < 2:
        raise ValueError("features/bins inválidos para referência de drift")
    reference: dict[str, Any] = {"method": "population_stability_index", "bins": int(bins), "features": {}}
    for column in features.columns:
        values = pd.to_numeric(features[column], errors="coerce").to_numpy(dtype=float)
        values = values[np.isfinite(values)]
        if not values.size:
            raise ValueError(f"feature sem valores finitos: {column}")
        quantiles = np.quantile(values, np.linspace(0.0, 1.0, bins + 1))
        edges = np.unique(quantiles[1:-1])
        edges = np.concatenate(([-np.finfo(float).max], edges, [np.finfo(float).max])).astype(float)
        counts, _ = np.histogram(values, bins=edges)
        probabilities = (counts.astype(float) + 1e-6) / (counts.sum() + 1e-6 * len(counts))
        reference["features"][str(column)] = {
            "edges": [float(edge) for edge in edges],
            "expected": probabilities.tolist(),
        }
    return reference


def population_stability_index(expected: list[float], observed: list[float]) -> float:
    expected_array = np.asarray(expected, dtype=float)
    observed_array = np.asarray(observed, dtype=float)
    if expected_array.shape != observed_array.shape or expected_array.ndim != 1 or not len(expected_array):
        raise ValueError("histogramas de PSI incompatíveis")
    epsilon = 1e-6
    expected_array = np.clip(expected_array, epsilon, None)
    observed_array = np.clip(observed_array, epsilon, None)
    expected_array /= expected_array.sum()
    observed_array /= observed_array.sum()
    return float(np.sum((observed_array - expected_array) * np.log(observed_array / expected_array)))


def assess_drift(
    reference: dict[str, Any],
    recent_features: pd.DataFrame,
    *,
    baseline_metrics: dict[str, Any] | None = None,
    recent_metrics: dict[str, Any] | None = None,
    psi_threshold: float = 0.25,
    max_balanced_accuracy_drop: float = 0.10,
    max_brier_increase: float = 0.05,
) -> dict[str, Any]:
    """Compara PSI por feature e degradação contra métricas OOS congeladas."""
    if not isinstance(recent_features, pd.DataFrame) or recent_features.empty:
        raise ValueError("janela de features recente vazia")
    thresholds = (psi_threshold, max_balanced_accuracy_drop, max_brier_increase)
    if any(not np.isfinite(value) or float(value) < 0 for value in thresholds):
        raise ValueError("limiares de drift devem ser finitos e não negativos")
    reference_features = reference.get("features") or {}
    missing = sorted(set(reference_features) - set(map(str, recent_features.columns)))
    if missing:
        raise ValueError(f"schema recente sem features de referência: {missing}")
    psi_by_feature: dict[str, float] = {}
    for column, profile in reference_features.items():
        values = pd.to_numeric(recent_features[column], errors="coerce").to_numpy(dtype=float)
        values = values[np.isfinite(values)]
        if not values.size:
            psi_by_feature[str(column)] = 1_000_000.0
            continue
        edges = np.asarray(profile["edges"], dtype=float)
        counts, _ = np.histogram(values, bins=edges)
        observed = (counts.astype(float) + 1e-6) / (counts.sum() + 1e-6 * len(counts))
        psi_by_feature[str(column)] = population_stability_index(profile["expected"], observed.tolist())

    baseline = baseline_metrics or {}
    recent = recent_metrics or {}
    baseline_balanced = baseline.get("balanced_accuracy")
    recent_balanced = recent.get("balanced_accuracy")
    baseline_brier = baseline.get("brier_score")
    recent_brier = recent.get("brier_score")
    balanced_drop = (
        float(baseline_balanced) - float(recent_balanced)
        if baseline_balanced is not None and recent_balanced is not None else None
    )
    brier_increase = (
        float(recent_brier) - float(baseline_brier)
        if baseline_brier is not None and recent_brier is not None else None
    )
    data_drift = any(value >= float(psi_threshold) for value in psi_by_feature.values())
    performance_drift = bool(
        (balanced_drop is not None and balanced_drop >= float(max_balanced_accuracy_drop))
        or (brier_increase is not None and brier_increase >= float(max_brier_increase))
    )
    return {
        "status": "drift_detected" if data_drift or performance_drift else "within_threshold",
        "hold": bool(data_drift or performance_drift),
        "data_drift": bool(data_drift),
        "performance_drift": performance_drift,
        "psi_threshold": float(psi_threshold),
        "psi_by_feature": psi_by_feature,
        "max_psi": max(psi_by_feature.values(), default=0.0),
        "baseline_balanced_accuracy": baseline_balanced,
        "recent_balanced_accuracy": recent_balanced,
        "balanced_accuracy_drop": balanced_drop,
        "baseline_brier_score": baseline_brier,
        "recent_brier_score": recent_brier,
        "brier_increase": brier_increase,
        "max_balanced_accuracy_drop": float(max_balanced_accuracy_drop),
        "max_brier_increase": float(max_brier_increase),
    }


def _write_hold_state(model_dir: Path, payload: dict[str, Any]) -> None:
    path = model_dir / "drift_status.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def _persisted_hold(model_dir: Path) -> bool:
    path = model_dir / "drift_status.json"
    if not path.exists():
        return False
    try:
        return bool(json.loads(path.read_text(encoding="utf-8")).get("hold", True))
    except (OSError, json.JSONDecodeError, AttributeError):
        return True


def _restore_backup(model_dir: Path, backup_path: Any, expected_hash: Any) -> tuple[bool, str | None]:
    if not backup_path:
        return False, None
    backup = Path(str(backup_path))
    required = ("rf_model.joblib", "xgb_model.joblib", "ensemble_metadata.json")
    if not backup.is_dir() or not all((backup / name).is_file() for name in required):
        return False, None
    if not expected_hash or artifact_sha256(backup) != str(expected_hash):
        raise ValueError("hash do backup não confere; restauração bloqueada e HOLD mantido")
    prior_version = None
    try:
        previous_metadata = json.loads((backup / "ensemble_metadata.json").read_text(encoding="utf-8"))
        prior_version = previous_metadata.get("model_version")
    except (OSError, json.JSONDecodeError):
        pass
    # Drift hold is written before restoration; a partial filesystem failure remains fail-closed.
    for name in required:
        shutil.copy2(backup / name, model_dir / name)
    return True, str(prior_version) if prior_version else None


def monitor_model_drift(
    dataset_path: str | Path,
    model_dir: str | Path,
    *,
    registry_store: Any | None = None,
    window_rows: int = 256,
    min_rows: int = 30,
    psi_threshold: float = 0.25,
    max_balanced_accuracy_drop: float = 0.10,
    max_brier_increase: float = 0.05,
    report_path: str | Path | None = "docs/reports/model-drift-latest.json",
) -> dict[str, Any]:
    """Avalia dataset rotulado recente; drift escreve hold e restaura backup, se houver."""
    if int(window_rows) < 1 or int(min_rows) < 1:
        raise ValueError("window_rows e min_rows devem ser positivos")
    root = Path(model_dir)
    metadata_path = root / "ensemble_metadata.json"
    if not metadata_path.is_file():
        raise FileNotFoundError("metadados do modelo ausentes; monitor bloqueado")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    reference = metadata.get("drift_reference")
    if not isinstance(reference, dict) or not reference.get("features"):
        raise ValueError("modelo sem perfil de referência; não é possível monitorar drift")
    ohlcv = load_ohlcv(dataset_path)
    integrity = validate_ohlcv(ohlcv, require_closed=True, reject_gaps=False, min_coverage=0.95)
    features, labels = FeaturePipeline().build_supervised(
        ohlcv,
        int(metadata.get("horizon", 3)),
        float(metadata.get("buy_threshold", 0.001)),
        float(metadata.get("sell_threshold", -0.001)),
    )
    if len(features) < int(min_rows):
        insufficient = {
            "status": "insufficient_observations",
            "hold": _persisted_hold(root),
            "rows": int(len(features)),
            "minimum_rows": int(min_rows),
            "dataset_integrity": integrity,
        }
        _write_drift_report(insufficient, report_path)
        return insufficient
    features = features.tail(int(window_rows))
    labels = labels.reindex(features.index)
    model = EnsembleModel(str(root))
    probabilities = model.predict_proba(features)
    recent_metrics = probability_metrics(labels.to_numpy(dtype=int), probabilities)
    stored_wf = (metadata.get("walk_forward_metrics") or {}).get("aggregate", {})
    baseline = stored_wf.get("model_classification") or {}
    assessed = assess_drift(
        reference,
        features,
        baseline_metrics=baseline,
        recent_metrics=recent_metrics,
        psi_threshold=psi_threshold,
        max_balanced_accuracy_drop=max_balanced_accuracy_drop,
        max_brier_increase=max_brier_increase,
    )
    result: dict[str, Any] = {
        **assessed,
        "model_version": metadata.get("model_version"),
        "reference_dataset_sha256": str(metadata.get("dataset_sha256", "")),
        "recent_dataset_sha256": sha256_file(dataset_path) if Path(dataset_path).is_file() else sha256_frame(ohlcv),
        "recent_rows": int(len(features)),
        "dataset_integrity": integrity,
        "recent_metrics": recent_metrics,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "rollback_performed": False,
    }
    if assessed["hold"]:
        # Antes do rollback: qualquer falha posterior mantém o runtime em HOLD.
        result["status"] = "drift_detected_hold"
        _write_hold_state(root, {"hold": True, **result})
        try:
            rollback_done, restored_version = _restore_backup(
                root,
                metadata.get("rollback_backup"),
                metadata.get("rollback_backup_sha256"),
            )
        except (OSError, ValueError) as exc:
            rollback_done, restored_version = False, None
            result["rollback_error"] = str(exc)
            logger.exception("Falha no rollback de artefatos; drift hold continua ativo")
        result["rollback_performed"] = rollback_done
        result["restored_version"] = restored_version
        if registry_store is not None and result.get("model_version"):
            try:
                registry_store.mark_rollback(str(result["model_version"]), restored_version)
            except Exception as exc:
                result["registry_error"] = str(exc)
                logger.exception("Falha ao atualizar registry após drift; runtime continua em HOLD")
        logger.error("MODEL DRIFT ALERT: version=%s, max_psi=%.4f, rollback=%s; runtime permanece em HOLD", result.get("model_version"), result.get("max_psi", 0.0), rollback_done)
        _write_hold_state(root, {"hold": True, **result})
    elif _persisted_hold(root):
        result["status"] = "hold_retained_manual_review_required"
        result["hold"] = True
        logger.warning("Drift retornou à faixa, mas HOLD persistente não é removido automaticamente")
    else:
        result["hold"] = False
    _write_drift_report(result, report_path)
    return result


def _write_drift_report(result: dict[str, Any], destination: str | Path | None) -> None:
    if destination is None:
        return
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", help="CSV/Parquet OHLCV recente com timestamps e candles fechados")
    parser.add_argument("--model-dir", default="models")
    parser.add_argument("--window-rows", type=int, default=256)
    parser.add_argument("--min-rows", type=int, default=30)
    parser.add_argument("--psi-threshold", type=float, default=0.25)
    parser.add_argument("--max-balanced-accuracy-drop", type=float, default=0.10)
    parser.add_argument("--max-brier-increase", type=float, default=0.05)
    parser.add_argument("--report-path", default="docs/reports/model-drift-latest.json")
    args = parser.parse_args()
    from config.settings import settings
    from database_manager import DatabaseManager
    from learning.model_registry import ModelRegistryStore

    db_manager = DatabaseManager(settings.DATABASE_URL)
    try:
        db_manager.create_tables()
        result = monitor_model_drift(
            args.dataset,
            args.model_dir,
            registry_store=ModelRegistryStore(db_manager),
            window_rows=args.window_rows,
            min_rows=args.min_rows,
            psi_threshold=args.psi_threshold,
            max_balanced_accuracy_drop=args.max_balanced_accuracy_drop,
            max_brier_increase=args.max_brier_increase,
            report_path=args.report_path,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        if result.get("hold"):
            raise SystemExit(2)
    finally:
        db_manager.engine.dispose()


if __name__ == "__main__":
    main()
