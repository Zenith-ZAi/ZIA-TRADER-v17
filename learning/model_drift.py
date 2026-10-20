"""Monitor de drift de dados/performance com hold persistente e rollback seguro."""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ai.ensemble_model import EnsembleModel
from ai.train_ensemble import load_ohlcv
from core.dataset_integrity import sha256_file, sha256_frame, validate_ohlcv
from core.feature_pipeline import FeaturePipeline
from learning.model_validation import _net_returns, _return_summary, probability_metrics
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
    baseline_class_distribution: dict[str, float] | None = None,
    recent_class_distribution: dict[str, float] | None = None,
    max_class_distribution_delta: float = 0.15,
) -> dict[str, Any]:
    """Compara PSI por feature e degradação contra métricas OOS congeladas."""
    if not isinstance(recent_features, pd.DataFrame) or recent_features.empty:
        raise ValueError("janela de features recente vazia")
    thresholds = (psi_threshold, max_balanced_accuracy_drop, max_brier_increase, max_class_distribution_delta)
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
    class_distribution_delta = None
    if baseline_class_distribution is not None and recent_class_distribution is not None:
        try:
            baseline_values = {str(key): float(value) for key, value in baseline_class_distribution.items()}
            recent_values = {str(key): float(value) for key, value in recent_class_distribution.items()}
            values = [*baseline_values.values(), *recent_values.values()]
            if not baseline_values or not recent_values or any(not np.isfinite(value) or value < 0.0 for value in values):
                raise ValueError("distribuição de classes inválida")
            baseline_total, recent_total = sum(baseline_values.values()), sum(recent_values.values())
            if baseline_total <= 0.0 or recent_total <= 0.0:
                raise ValueError("distribuição de classes sem massa")
            all_classes = set(baseline_values) | set(recent_values)
            class_distribution_delta = max(
                abs(baseline_values.get(label, 0.0) / baseline_total - recent_values.get(label, 0.0) / recent_total)
                for label in all_classes
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("distribuição de classes inválida") from exc
    class_drift = class_distribution_delta is not None and class_distribution_delta >= float(max_class_distribution_delta)
    data_drift = any(value >= float(psi_threshold) for value in psi_by_feature.values()) or class_drift
    baseline_net = baseline.get("net_return_metrics") if isinstance(baseline.get("net_return_metrics"), dict) else {}
    recent_net = recent.get("net_return_metrics") if isinstance(recent.get("net_return_metrics"), dict) else {}
    baseline_net_mean = baseline_net.get("mean_net_block_return")
    recent_net_mean = recent_net.get("mean_net_block_return")
    net_return_drop = float(baseline_net_mean) - float(recent_net_mean) if baseline_net_mean is not None and recent_net_mean is not None else None
    net_performance_drift = bool(
        net_return_drop is not None and float(baseline_net_mean) > 0.0 and float(recent_net_mean) <= 0.0
    )
    performance_drift = bool(
        (balanced_drop is not None and balanced_drop >= float(max_balanced_accuracy_drop))
        or (brier_increase is not None and brier_increase >= float(max_brier_increase))
        or net_performance_drift
    )
    return {
        "status": "drift_detected" if data_drift or performance_drift else "within_threshold",
        "hold": bool(data_drift or performance_drift),
        "data_drift": bool(data_drift),
        "performance_drift": performance_drift,
        "class_drift": bool(class_drift),
        "class_distribution_delta": class_distribution_delta,
        "max_class_distribution_delta": float(max_class_distribution_delta),
        "baseline_net_mean_block_return": baseline_net_mean,
        "recent_net_mean_block_return": recent_net_mean,
        "net_mean_return_drop": net_return_drop,
        "net_performance_drift": net_performance_drift,
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


def _read_persisted_state(model_dir: Path) -> dict[str, Any]:
    path = model_dir / "drift_status.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        return value if isinstance(value, dict) else {"hold": True}
    except (OSError, json.JSONDecodeError):
        return {"hold": True, "status": "unreadable_persisted_state"}


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
    max_class_distribution_delta: float = 0.15,
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
    model = EnsembleModel(str(root), registry_store=registry_store, require_active_registry=True)
    if not model.is_trained:
        raise RuntimeError(f"monitor bloqueado: artefato não ativo/aprovado ({model.load_status})")
    probabilities = model.predict_proba(features)
    recent_metrics = probability_metrics(labels.to_numpy(dtype=int), probabilities)
    recent_class_distribution = {
        str(int(label)): float(count)
        for label, count in labels.value_counts(normalize=True).to_dict().items()
    }
    training_config = metadata.get("training_config") or {}
    total_cost_bps = float(training_config.get("transaction_cost_bps", 0.0)) + float(training_config.get("slippage_bps", 0.0))
    if not np.isfinite(total_cost_bps) or total_cost_bps < 0.0:
        raise ValueError("premissa de custo/slippage inválida no manifesto")
    close = pd.to_numeric(ohlcv["close"], errors="coerce").astype(float)
    horizon = int(metadata.get("horizon", 3))
    forward_returns = (close.shift(-horizon) / close - 1.0).reindex(features.index).to_numpy(dtype=float)
    if not np.isfinite(forward_returns).all():
        raise ValueError("retornos forward não finitos na janela rotulada de drift")
    predicted_classes = probabilities.argmax(axis=1)
    positions = np.where(predicted_classes == 2, 1.0, np.where(predicted_classes == 0, -1.0, 0.0))
    net_returns, trade_counts = _net_returns(positions, forward_returns, total_cost_bps)
    recent_metrics["net_return_metrics"] = _return_summary(net_returns.tolist(), int(trade_counts.sum()))
    recent_metrics["cost_assumption_bps"] = total_cost_bps
    stored_wf = (metadata.get("walk_forward_metrics") or {}).get("aggregate", {})
    baseline = dict(metadata.get("test_metrics") or {})
    baseline_classification = stored_wf.get("model_classification") or {}
    baseline.update({key: value for key, value in baseline_classification.items() if key not in baseline})
    baseline_class_distribution = metadata.get("training_class_distribution")
    assessed = assess_drift(
        reference,
        features,
        baseline_metrics=baseline,
        recent_metrics=recent_metrics,
        psi_threshold=psi_threshold,
        max_balanced_accuracy_drop=max_balanced_accuracy_drop,
        max_brier_increase=max_brier_increase,
        baseline_class_distribution=baseline_class_distribution,
        recent_class_distribution=recent_class_distribution,
        max_class_distribution_delta=max_class_distribution_delta,
    )
    result: dict[str, Any] = {
        **assessed,
        "model_version": metadata.get("model_version"),
        "reference_dataset_sha256": str(metadata.get("dataset_sha256", "")),
        "recent_dataset_sha256": sha256_file(dataset_path) if Path(dataset_path).is_file() else sha256_frame(ohlcv),
        "recent_rows": int(len(features)),
        "dataset_integrity": integrity,
        "recent_metrics": recent_metrics,
        "recent_class_distribution": recent_class_distribution,
        "baseline_class_distribution": baseline_class_distribution,
        "cost_assumption_bps": total_cost_bps,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "rollback_performed": False,
    }
    if assessed["hold"]:
        # Antes do rollback: qualquer falha posterior mantém o runtime em HOLD.
        result["status"] = "drift_detected_hold"
        previous_state = _read_persisted_state(root)
        previous_incident = previous_state.get("incident") if isinstance(previous_state.get("incident"), dict) else {}
        same_incident = previous_state.get("hold") is True and previous_state.get("model_version") == result.get("model_version")
        result["incident"] = {
            "incident_id": previous_incident.get("incident_id") if same_incident else uuid.uuid4().hex,
            "first_detected_at": previous_incident.get("first_detected_at") if same_incident else result["checked_at"],
            "last_detected_at": result["checked_at"],
            "consecutive_drift_checks": int(previous_incident.get("consecutive_drift_checks", 0)) + 1 if same_incident else 1,
            "requires_manual_review": True,
        }
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
        previous_state = _read_persisted_state(root)
        result["incident"] = previous_state.get("incident", {"requires_manual_review": True})
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
